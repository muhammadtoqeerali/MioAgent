"""Goal -> local plan -> immutable-test draft -> approve -> verify -> bounded repair.

Preview safety limits: one approved local model, one GPU, stdlib unittest only,
no generic shell/browser/network tools, no automatic Git publication of project code.
Use: python -m scripts.engineer_project goal.json [--execute]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from mio.config import Settings
from mio.engineering_engine import (
    EngineeringStop,
    Goal,
    parse_goal,
    parse_plan,
    validate_review_draft,
)
from mio.llm import ModelRouter
from mio.model_fleet import FleetRouter, load_policy
from scripts.autonomous_repair import (
    ID_PATTERN,
    LocalAPI,
    RunStopped,
    run_cycle,
    save_atomic_private,
    test_fingerprints,
)
from scripts.native_runtime import RUNTIME, get_token, load_model_config, setup_runtime

API_ROOT = "http://127.0.0.1:8000/api"
DRAFT_TIMEOUT = 660


class EngineeringAPI(LocalAPI):
    """Extend the existing guarded API only with its documented create-project endpoint."""

    def create_project(self, goal: Goal, plan: dict) -> dict:
        data = json.dumps({
            "title": goal.title, "requirements": goal.project_requirements(plan),
        }).encode("utf-8")
        request = Request(
            f"{API_ROOT}/projects", data=data, method="POST",
            headers={"Authorization": f"Bearer {self.token}",
                     "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=20) as response:
                result = json.load(response)
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            raise EngineeringStop(f"Local project creation failed: {exc}") from exc
        if not isinstance(result, dict) or not ID_PATTERN.fullmatch(result.get("id", "")):
            raise EngineeringStop("Project API returned an invalid identifier")
        if result.get("status") != "drafting":
            raise EngineeringStop("Created project is not drafting")
        return result

    def retry_failed_draft(self, project_id: str) -> dict:
        """Requeue one previously failed draft on the same project identity."""
        if not ID_PATTERN.fullmatch(project_id):
            raise EngineeringStop("Invalid recovery project ID")
        result = self.call(f"projects/{project_id}/retry-draft", post=True)
        if result.get("id") != project_id or result.get("status") != "drafting":
            raise EngineeringStop("Draft retry did not return the same project")
        return result

    def lock_tests(self, project_id: str, goal: Goal) -> dict:
        if not ID_PATTERN.fullmatch(project_id):
            raise EngineeringStop("Invalid project ID for acceptance locking")
        payload = json.dumps({"approved": True,
                              "tests": dict(goal.acceptance_tests)}).encode("utf-8")
        request = Request(
            f"{API_ROOT}/projects/{project_id}/acceptance", data=payload, method="POST",
            headers={"Authorization": f"Bearer {self.token}",
                     "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=20) as response:
                result = json.load(response)
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            raise EngineeringStop(f"Trusted acceptance lock failed: {exc}") from exc
        if not isinstance(result, dict) or result.get("id") != project_id:
            raise EngineeringStop("Acceptance lock returned the wrong project")
        return result


def wait_project(api: LocalAPI, project_id: str, target: str, *, timeout: int = DRAFT_TIMEOUT,
                 pause=time.sleep, now=time.monotonic) -> dict:
    if not ID_PATTERN.fullmatch(project_id):
        raise EngineeringStop("Invalid project identifier")
    deadline = now() + timeout
    while now() < deadline:
        response = api.call(f"projects/{project_id}")
        status = response.get("status")
        if status == target:
            return response
        if status in {"failed", "canceled", "completed" if target == "review" else "review"}:
            raise EngineeringStop(f"Project stopped at {status}: {str(response.get('error', ''))[:250]}")
        if status not in ({"drafting"} if target == "review" else {"applying"}):
            raise EngineeringStop(f"Unexpected project status: {status}")
        pause(2)
    raise EngineeringStop(f"Timed out waiting for project to reach {target}")


async def local_plan(goal: Goal) -> tuple[dict, str]:
    """Use the configured local Ollama model, never cloud or remote inference."""
    config = load_model_config()
    if config.get("MIO_LOCAL_MODEL") != "gpt-oss:20b":
        raise EngineeringStop("This preview is pinned to the validated local gpt-oss:20b model")
    settings = Settings(
        _env_file=None, mio_api_token=get_token(),
        mio_local_model="gpt-oss:20b",
        mio_local_base_url="http://127.0.0.1:11434/v1",
        mio_model_route="local", mio_allow_cloud=False,
        mio_cloud_api_key="",
    )
    from mio.engineering_engine import PLANNER_SYSTEM

    content = json.dumps({
        "goal": goal.requirements,
        "criteria": {f"C{i}": x for i, x in enumerate(goal.criteria, 1)},
        "test_paths": [p for p, _ in goal.acceptance_tests],
    }, ensure_ascii=False)
    fleet = load_policy()
    router = FleetRouter(settings, "planning", fleet) if fleet else ModelRouter(settings)
    messages = [
        {"role": "system", "content": PLANNER_SYSTEM},
        {"role": "user", "content": content},
    ]
    for retry in range(2):
        response = await router.complete(messages, max_tokens=1200)
        if response.provider != "local" or (fleet is None and response.model != "gpt-oss:20b"):
            raise EngineeringStop("Planner used an unexpected model/provider")
        try:
            roles = None
            if fleet is not None:
                roles = {role: fleet.roles[role][0] for role in ("planning", "coding", "review")}
                roles["planning"] = response.model
            return parse_plan(response.text, goal, role_models=roles), response.model
        except EngineeringStop:
            if retry:
                raise
            # One format/coverage retry, no tool execution and no cloud fallback.
            messages = [
                messages[0],
                messages[1],
                {"role": "user", "content": "Your prior plan was invalid. Return ONLY the exact "
                 "JSON schema requested, 3..7 tasks, and reference all supplied criteria. "
                 "No prose or Markdown fences."},
            ]
    raise EngineeringStop("Unexpected planner retry state")


def execute_goal(api: EngineeringAPI, goal: Goal, plan: dict, *, record,
                 repair_runner=run_cycle) -> dict:
    """Each API action is sequenced behind the source/acceptance policy gates."""
    status = api.call("status")
    if not status.get("project_mode_enabled") or not status.get("sandbox_verify_enabled"):
        raise EngineeringStop("Local Project Mode and Bubblewrap verification must be enabled")
    record({"event": "plan_validated", "mapped_criteria": plan["criteria_mapped"]})
    created = api.create_project(goal, plan)
    project_id = created["id"]
    record({"event": "project_created", "project_id": project_id})
    return finish_goal(api, goal, project_id, record=record, repair_runner=repair_runner)


def finish_goal(api: EngineeringAPI, goal: Goal, project_id: str, *, record,
                repair_runner=run_cycle) -> dict:
    """Continue from the draft stage; no plan or project is recreated."""
    wait_project(api, project_id, "review")
    review = api.lock_tests(project_id, goal)
    evidence = validate_review_draft(review, goal)
    record({"event": "user_acceptance_tests_verified", "project_id": project_id,
            "test_sha256": evidence["test_sha256"],
            "test_cases": evidence["test_cases"], "source_files": evidence["source_files"]})
    api.call(f"projects/{project_id}/apply", post=True)
    applied = wait_project(api, project_id, "completed")
    if test_fingerprints(applied) != evidence["test_sha256"]:
        raise EngineeringStop("Applied project acceptance-test bytes have changed")
    record({"event": "source_applied", "project_id": project_id})

    def relay(step: dict) -> None:
        # Existing bounded runner verifies unchanged test hashes on every revision.
        tail = step.get("history", [])
        record({"event": "repair_progress", "project_id": project_id,
                "steps": len(tail), "current_project": step.get("current_project")})

    result = repair_runner(api, project_id, attempts=goal.max_repairs, report=relay)
    if result.get("outcome") not in {"passed", "repair_limit"}:
        raise EngineeringStop("Unexpected repair-runner result")
    record({"event": "run_finished", "outcome": result["outcome"],
            "final_project": result.get("project_id"), "repairs": result.get("attempts")})
    return {
        "outcome": result["outcome"], "project_id": result["project_id"],
        "repairs": result["attempts"], "test_sha256": evidence["test_sha256"],
        "test_cases": evidence["test_cases"], "history": result["history"],
        "acceptance": "Original user-authored test bytes were independently checked",
        "caveat": "Passing specified tests does not prove all real-world requirements or security.",
    }


def _approved_report_model(name: object) -> bool:
    if name == "gpt-oss:20b":
        return True  # Backward compatibility for already verified v0.4A-C runs.
    fleet = load_policy()
    return isinstance(name, str) and fleet is not None and name in fleet.roles["planning"]


def validated_resume_report(path: Path, goal: Goal) -> tuple[dict, dict, str]:
    """Only re-use a single private stopped plan for exactly the same goal."""
    import os
    import stat

    if not path.is_file() or path.is_symlink():
        raise EngineeringStop("No private engineering run exists to resume")
    info = path.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise EngineeringStop("Recovery report must be user-owned and private")
    report = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(report, dict) or report.get("goal_sha256") != goal.digest
            or report.get("state") != "stopped" or not _approved_report_model(report.get("planner_model"))):
        raise EngineeringStop("Only a stopped, matching local-model report can be resumed")
    events = report.get("events")
    if not isinstance(events, list):
        raise EngineeringStop("Recovery event history is missing")
    created = [e for e in events if isinstance(e, dict) and e.get("event") == "project_created"]
    if (len(created) != 1 or any(not isinstance(e, dict) or e.get("event") not in
                                {"plan_validated", "project_created"} for e in events)):
        raise EngineeringStop("Run advanced beyond draft stage; manual review required")
    project_id = created[0].get("project_id")
    if not isinstance(project_id, str) or not ID_PATTERN.fullmatch(project_id):
        raise EngineeringStop("Recovery project ID invalid")
    saved = report.get("plan")
    if not isinstance(saved, dict) or not isinstance(saved.get("tasks"), list):
        raise EngineeringStop("Saved engineering plan is invalid")
    clean_tasks = [{k: t[k] for k in ("role", "action", "criteria")}
                   for t in saved["tasks"] if isinstance(t, dict)
                   and all(k in t for k in ("role", "action", "criteria"))]
    selected = {task["role"]: task["model"] for task in saved["tasks"]}
    plan = parse_plan(json.dumps({"tasks": clean_tasks}), goal,
                      role_models=selected if saved.get("routing") != "local gpt-oss:20b only, no downloaded skills or remote GPUs" else None)
    if plan != saved:
        raise EngineeringStop("Saved plan has changed since validation")
    return report, plan, project_id


def resume_goal(api: EngineeringAPI, goal: Goal, plan: dict, project_id: str,
                *, record, repair_runner=run_cycle) -> dict:
    state = api.call("status")
    if not state.get("project_mode_enabled") or not state.get("sandbox_verify_enabled"):
        raise EngineeringStop("Project Mode and sandbox must remain enabled")
    original = api.call(f"projects/{project_id}")
    if (original.get("title") != goal.title
            or original.get("requirements") != goal.project_requirements(plan)
            or original.get("status") != "failed" or original.get("draft") is not None
            or original.get("workspace") is not None or original.get("apply_task_id") is not None
            or "local model" not in str(original.get("error", ""))):
        raise EngineeringStop("Failed project does not match saved goal and draft failure")
    api.retry_failed_draft(project_id)
    record({"event": "failed_draft_requeued", "project_id": project_id})
    return finish_goal(api, goal, project_id, record=record, repair_runner=repair_runner)


def validated_restart_report(path: Path, goal: Goal) -> tuple[dict, dict, str]:
    """One fresh project attempt using the verified failed goal and saved plan."""
    import os
    import stat

    if not path.is_file() or path.is_symlink():
        raise EngineeringStop("Missing original private engineering report")
    info = path.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise EngineeringStop("Original report must be user-owned and private")
    report = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(report, dict) or report.get("goal_sha256") != goal.digest
            or report.get("state") != "stopped"
            or not _approved_report_model(report.get("planner_model"))):
        raise EngineeringStop("Original goal is not an eligible stopped local attempt")
    events = report.get("events")
    if not isinstance(events, list):
        raise EngineeringStop("Original event history missing")
    allowed = {"plan_validated", "project_created", "failed_draft_requeued"}
    if any(not isinstance(e, dict) or e.get("event") not in allowed for e in events):
        raise EngineeringStop("Original run progressed beyond drafting; refusing restart")
    created = [e.get("project_id") for e in events if e.get("event") == "project_created"]
    if len(created) != 1 or not isinstance(created[0], str) or not ID_PATTERN.fullmatch(created[0]):
        raise EngineeringStop("Original project identity is ambiguous")
    saved = report.get("plan")
    if not isinstance(saved, dict) or not isinstance(saved.get("tasks"), list):
        raise EngineeringStop("Original verified plan missing")
    raw_tasks = []
    for task in saved["tasks"]:
        if not isinstance(task, dict) or not all(x in task for x in ("role", "action", "criteria")):
            raise EngineeringStop("Original plan is malformed")
        raw_tasks.append({key: task[key] for key in ("role", "action", "criteria")})
    selected = {task["role"]: task["model"] for task in saved["tasks"]}
    verified = parse_plan(json.dumps({"tasks": raw_tasks}), goal,
                          role_models=selected if saved.get("routing") != "local gpt-oss:20b only, no downloaded skills or remote GPUs" else None)
    if verified != saved:
        raise EngineeringStop("Original plan no longer validates")
    return report, verified, created[0]


def assert_fresh_restart_allowed(api: EngineeringAPI, goal: Goal, plan: dict,
                                 previous_id: str) -> None:
    """Before reserving a retry report, confirm the original is an untouched failed draft."""
    state = api.call("status")
    if not state.get("project_mode_enabled") or not state.get("sandbox_verify_enabled"):
        raise EngineeringStop("Local Project Mode and sandbox must be enabled")
    original = api.call(f"projects/{previous_id}")
    if (original.get("status") != "failed" or original.get("draft") is not None
            or original.get("title") != goal.title
            or original.get("requirements") != goal.project_requirements(plan)
            or original.get("workspace") is not None
            or original.get("apply_task_id") is not None):
        raise EngineeringStop("Original project is not an unchanged failed draft")


def restart_failed_goal(api: EngineeringAPI, goal: Goal, plan: dict, previous_id: str,
                        *, record, repair_runner=run_cycle) -> dict:
    """Preserve the exhausted original project; create one separately audited attempt."""
    assert_fresh_restart_allowed(api, goal, plan, previous_id)
    record({"event": "plan_reused", "previous_project": previous_id})
    created = api.create_project(goal, plan)
    record({"event": "project_created", "project_id": created["id"]})
    return finish_goal(api, goal, created["id"], record=record,
                       repair_runner=repair_runner)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("goal", type=Path, help="JSON goal contract with user-authored tests")
    parser.add_argument("--execute", action="store_true", help="Delegate bounded project write/test/repair")
    parser.add_argument("--resume", action="store_true", help="Once-only recover a failed local draft")
    parser.add_argument("--restart-failed", action="store_true",
                        help="One fresh project attempt with saved plan after exhausted recovery")
    args = parser.parse_args()
    try:
        if args.resume and args.restart_failed:
            raise EngineeringStop("Choose --resume or --restart-failed, not both")
        if (args.resume or args.restart_failed) and not args.execute:
            raise EngineeringStop("Recovery requires explicit --execute")
        if not args.goal.is_file() or args.goal.is_symlink():
            raise EngineeringStop("Provide an existing regular goal JSON file")
        goal = parse_goal(args.goal.read_bytes())
        setup_runtime()
        runs = RUNTIME / "engineering-runs"
        report_path = runs / f"{goal.digest}.json"
        if args.restart_failed:
            previous_report, plan, project_id = validated_restart_report(report_path, goal)
            retry_path = runs / f"{goal.digest}.retry1.json"
            if retry_path.exists() or retry_path.is_symlink():
                raise EngineeringStop("A fresh recovery attempt already exists; no repeated replay")
            assert_fresh_restart_allowed(EngineeringAPI(get_token()), goal, plan, project_id)
            runs.mkdir(mode=0o700, exist_ok=True)
            model = previous_report["planner_model"]
            report_path = retry_path
            report = {"goal_sha256": goal.digest, "planner_model": model,
                      "plan": plan, "events": [], "state": "starting",
                      "restarted_from": project_id,
                      "original_report_state": previous_report["state"]}
            save_atomic_private(report_path, report)
            print(json.dumps({"restart_from_failed_project": project_id, "model": model,
                              "plan": plan, "goal_sha256": goal.digest}, indent=2), flush=True)
        elif args.resume:
            report, plan, project_id = validated_resume_report(report_path, goal)
            model = report["planner_model"]
            print(json.dumps({"resume_project": project_id, "model": model,
                              "plan": plan, "goal_sha256": goal.digest}, indent=2), flush=True)
        else:
            if args.execute and (report_path.exists() or report_path.is_symlink()):
                raise EngineeringStop("This goal already has a report; use --execute --resume for a failed draft")
            plan, model = asyncio.run(local_plan(goal))
            print(json.dumps({"model": model, "plan": plan,
                              "goal_sha256": goal.digest}, indent=2), flush=True)
            if not args.execute:
                print("PLAN ONLY: no files, projects or tests changed. Add --execute to delegate this goal.")
                return
            runs.mkdir(mode=0o700, exist_ok=True)
            report = {"goal_sha256": goal.digest, "planner_model": model,
                      "plan": plan, "events": [], "state": "starting"}
            save_atomic_private(report_path, report)

        def record(event: dict) -> None:
            report["events"].append({**event, "timestamp_utc_seconds": int(time.time())})
            save_atomic_private(report_path, report)

        try:
            if args.resume:
                report["state"] = "resuming"
                save_atomic_private(report_path, report)
                result = resume_goal(EngineeringAPI(get_token()), goal, plan,
                                     project_id, record=record)
            elif args.restart_failed:
                result = restart_failed_goal(EngineeringAPI(get_token()), goal, plan,
                                             project_id, record=record)
            else:
                result = execute_goal(EngineeringAPI(get_token()), goal, plan, record=record)
            report.update({"state": "finished", "result": result})
            save_atomic_private(report_path, report)
            print(json.dumps(result, indent=2))
        except (EngineeringStop, RunStopped, OSError) as exc:
            report.update({"state": "stopped", "error": str(exc)[:500]})
            save_atomic_private(report_path, report)
            raise
        finally:
            print(f"Private engineering run report: {report_path}")
    except (EngineeringStop, RunStopped, OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"STOPPED: {exc}\n")


if __name__ == "__main__":
    main()
