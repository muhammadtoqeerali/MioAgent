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
DRAFT_TIMEOUT = 240


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
    router = ModelRouter(settings)
    messages = [
        {"role": "system", "content": PLANNER_SYSTEM},
        {"role": "user", "content": content},
    ]
    for retry in range(2):
        response = await router.complete(messages, max_tokens=1200)
        if response.provider != "local" or response.model != "gpt-oss:20b":
            raise EngineeringStop("Planner used an unexpected model/provider")
        try:
            return parse_plan(response.text, goal), response.model
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("goal", type=Path, help="JSON goal contract with user-authored tests")
    parser.add_argument("--execute", action="store_true", help="Delegate bounded project write/test/repair")
    args = parser.parse_args()
    try:
        if not args.goal.is_file() or args.goal.is_symlink():
            raise EngineeringStop("Provide an existing regular goal JSON file")
        goal = parse_goal(args.goal.read_bytes())
        setup_runtime()
        plan, model = asyncio.run(local_plan(goal))
        print(json.dumps({"model": model, "plan": plan,
                          "goal_sha256": goal.digest}, indent=2), flush=True)
        if not args.execute:
            print("PLAN ONLY: no files, projects or tests changed. Add --execute to delegate this goal.")
            return
        runs = RUNTIME / "engineering-runs"
        runs.mkdir(mode=0o700, exist_ok=True)
        report_path = runs / f"{goal.digest}.json"
        if report_path.exists() or report_path.is_symlink():
            raise EngineeringStop("A run already exists for this goal; inspect its private report")
        report = {"goal_sha256": goal.digest, "planner_model": model,
                  "plan": plan, "events": [], "state": "starting"}
        save_atomic_private(report_path, report)

        def record(event: dict) -> None:
            report["events"].append({**event, "timestamp_utc_seconds": int(time.time())})
            save_atomic_private(report_path, report)

        try:
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
