"""MioAgent v0.4E: plan, patch and verify an existing Python repository.

Plan-only: python -m scripts.repo_engineer /abs/goal.json
Private sandbox trial: ... --execute
Owner-authorized original source update only after passing tests: ... --execute --apply
Never runs model-created commands, opens a network sandbox, or publishes Git.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path

from mio.model_fleet import FleetRouter, load_policy
from mio.repo_agent import (
    RepoGoal,
    RepoStop,
    apply_verified,
    context,
    diff,
    locked_snapshot,
    parse_edits,
    staged_snapshot,
    test_staged,
)
from mio.repo_agent import (
    diff as create_diff,
)
from mio.repo_agent import (
    sha as agent_hash,
)
from mio.sandbox_verify import preflight
from scripts.model_fleet import _settings
from scripts.native_runtime import RUNTIME, setup_runtime

CODE_SYSTEM = (
    "You are a repository coding agent. You are NOT allowed to execute tools or commands. "
    "Read the supplied tree and trusted tests. Respond with ONE JSON object only: "
    '{"edits":[{"path":"existing/allowed.py","content":"COMPLETE NEW Python file"}]}. '
    "Only rewrite file paths explicitly allowed by the owner. Do not modify tests, "
    "do not return a diff, do not include markdown, and preserve unrelated behavior. "
    "Use full, valid Python file content with correct escaped JSON newlines."
)
PLAN_SYSTEM = (
    "Outline the smallest way to satisfy the requested repository change. "
    'Return JSON only: {"steps":["inspect", "edit", "test"]}, 2..5 steps. '
    "No code or tool commands."
)


def private_dir() -> Path:
    root = RUNTIME / "repo-engineering"
    if root.is_symlink():
        raise RepoStop("Private run directory cannot be a symlink")
    root.mkdir(mode=0o700, exist_ok=True)
    if root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
        raise RepoStop("Repo-engineering run directory must be owner-only")
    return root


def atomic_report(folder: Path, data: dict) -> None:
    target = folder / "report.json"
    temporary = folder / "report.tmp"
    if target.is_symlink() or temporary.exists() or temporary.is_symlink():
        raise RepoStop("Unsafe or concurrent run report")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


async def propose(goal: RepoGoal, snapshot: dict[str, bytes], feedback: str,
                  router: FleetRouter) -> tuple[dict[str, bytes], str]:
    prompt = context(goal, snapshot, feedback)
    result = await router.complete([
        {"role": "system", "content": CODE_SYSTEM},
        {"role": "user", "content": f"APPROVED EDIT PATHS: {list(goal.editable)}\n\n{prompt}"},
    ], max_tokens=3072)
    edits = parse_edits(result.text, goal)
    return edits, result.model


async def run(goal: RepoGoal, *, apply: bool = False, plan_only: bool = True) -> dict:
    snapshot, pinned = locked_snapshot(goal)
    preview = {"root": str(goal.root), "goal_sha256": goal.digest(),
               "editable_files": list(goal.editable), "acceptance_tests": list(goal.tests),
               "acceptance_sha256": {p: pinned[p] for p in goal.tests},
               "tree_files": len(snapshot), "tree_bytes": sum(len(x) for x in snapshot.values()),
               "max_attempts": goal.max_attempts, "execute": not plan_only, "apply": apply}
    if plan_only:
        return preview
    if apply and not goal.editable:
        raise RepoStop("No source files allowed to apply")
    dest = private_dir() / goal.digest()
    if dest.exists() or dest.is_symlink():
        raise RepoStop(f"A run already exists for this exact goal; inspect {dest / 'report.json'}")
    dest.mkdir(mode=0o700)
    # Project source is not modified without --apply. Report records every outcome.
    report: dict = {"state": "started", **preview, "attempts": [], "created_unix": int(time.time())}
    atomic_report(dest, report)
    try:
        # Fail closed before model calls if OS sandbox isolation cannot be established.
        preflight(dest)
        baseline = dest / "baseline"
        staged_snapshot(baseline, snapshot)
        baseline_result = test_staged(baseline, goal.tests, pinned)
        report["baseline"] = {k: v for k, v in baseline_result.items() if k != "log"}
        atomic_report(dest, report)
        policy = load_policy()
        planner = FleetRouter(_settings(), "planning", policy)
        steps = None
        planner_model = None
        for plan_trial in range(2):
            print(f"=== PLANNING ATTEMPT {plan_trial + 1}/2 ===", flush=True)
            plan = await planner.complete([
                {"role": "system", "content": PLAN_SYSTEM},
                {"role": "user", "content": context(goal, snapshot)[:18_000]},
            ], max_tokens=1100)
            try:
                candidate = json.loads(plan.text.strip().removeprefix("```json").removesuffix("```").strip())
                steps = candidate.get("steps")
                if not isinstance(steps, list) or not 2 <= len(steps) <= 5 or not all(
                    isinstance(s, str) and 4 <= len(s) <= 200 for s in steps
                ):
                    raise ValueError("Invalid model plan")
                planner_model = plan.model
                break
            except (ValueError, AttributeError):
                if plan_trial == 0:
                    planner.advance()
        if steps is None:
            # Avoid blocking a repair solely because a model did not follow a
            # non-authoritative planning JSON format. Do not mislabel it as AI.
            steps = ["Inspect approved source and trusted tests",
                     "Edit explicitly approved application files",
                     "Run unchanged acceptance tests in the isolated verifier"]
            report["planner_fallback"] = "deterministic controller plan; model formatting failed"
        report["plan"] = steps
        report["planner_model"] = planner_model
        atomic_report(dest, report)
        router = FleetRouter(_settings(), "coding", policy)
        feedback = ""
        for attempt in range(1, goal.max_attempts + 1):
            print(f"=== CODING AND SANDBOX ATTEMPT {attempt}/{goal.max_attempts} ===", flush=True)
            stage = dest / f"attempt-{attempt}"
            # Create fresh staging files every time; no modified test bytes are inherited.
            staged_snapshot(stage, snapshot)
            event: dict = {"attempt": attempt}
            try:
                changes, model = await propose(goal, snapshot, feedback, router)
                event["model"] = model
                if not any(snapshot[p] != data for p, data in changes.items()):
                    raise RepoStop("Model proposed no actual source change")
                for path, raw in changes.items():
                    (stage / path).write_bytes(raw)
                result = test_staged(stage, goal.tests, pinned)
                event.update({"test": {k: v for k, v in result.items() if k != "log"},
                              "log_tail": result["log"][-2_500:],
                              "changed_files": sorted(changes)})
                print(f"Candidate: {model} | exact tests: {result['tests_run']} | outcome: {result['outcome']}",
                      flush=True)
                if result["passed"]:
                    patch = diff(snapshot, changes)
                    (dest / "changes.patch").write_text(patch, encoding="utf-8")
                    (dest / "changes.patch").chmod(0o600)
                    event["outcome"] = "passed"
                    report["attempts"].append(event)
                    report.update({"state": "passed", "model": model, "patch": str(dest / "changes.patch"),
                                   "tests_run": result["tests_run"]})
                    if apply:
                        report["applied"] = apply_verified(goal, snapshot, changes, dest)
                    atomic_report(dest, report)
                    return report
                feedback = "Previous candidate failed immutable tests:\n" + result["log"][-4_000:]
                event["outcome"] = "tests_failed"
            except RepoStop as exc:
                event["outcome"] = "invalid_draft"
                event["reason"] = str(exc)[:180]
                feedback = f"Previous draft rejected: {str(exc)[:180]}. Return valid complete JSON edits."
            report["attempts"].append(event)
            atomic_report(dest, report)
            # For a broken implementation or schema, favor an independently approved
            # model next. If only one model, a bounded retry uses the same provider.
            router.advance()
        report["state"] = "failed"
        report["reason"] = "All bounded proposed code revisions failed validation or acceptance tests"
        atomic_report(dest, report)
        return report
    except Exception as exc:
        report["state"] = "stopped"
        report["reason"] = f"{type(exc).__name__}: {str(exc)[:220]}"
        atomic_report(dest, report)
        raise


def apply_previous(goal: RepoGoal) -> dict:
    """Explicit second-stage approval: re-run tests, compare hashes, then apply.

    No model inference, no duplicate project; every source and test byte is
    compared to the frozen baseline before touching the original tree.
    """
    dest = private_dir() / goal.digest()
    record_file = dest / "report.json"
    if not record_file.is_file() or record_file.is_symlink():
        raise RepoStop("Previous private engineering report missing")
    if record_file.stat().st_mode & 0o077:
        raise RepoStop("Previous report must be private")
    report = json.loads(record_file.read_text(encoding="utf-8"))
    if report.get("state") != "passed" or "applied" in report or report.get("goal_sha256") != goal.digest():
        raise RepoStop("Only an unapplied, previously passing run may be approved")
    attempts = report.get("attempts")
    if not isinstance(attempts, list) or not attempts or attempts[-1].get("outcome") != "passed":
        raise RepoStop("No completed passing candidate is recorded")
    last = attempts[-1]
    if not isinstance(last.get("attempt"), int) or not 1 <= last["attempt"] <= goal.max_attempts:
        raise RepoStop("Invalid recorded candidate index")
    changed_paths = last.get("changed_files")
    if (not isinstance(changed_paths, list) or not changed_paths
            or len(set(changed_paths)) != len(changed_paths)
            or any(p not in goal.editable for p in changed_paths)):
        raise RepoStop("Recorded candidate contains non-allowlisted paths")
    original = dest / "baseline"
    stage = dest / f"attempt-{last['attempt']}"
    if not original.is_dir() or not stage.is_dir() or original.is_symlink() or stage.is_symlink():
        raise RepoStop("Original snapshot or passing candidate missing")
    for folder, paths in ((original, goal.editable + goal.tests), (stage, tuple(changed_paths) + goal.tests)):
        for name in paths:
            candidate = folder / name
            if (not candidate.is_file() or candidate.is_symlink()
                    or not candidate.resolve().is_relative_to(folder)):
                raise RepoStop("Prior run contains an unsafe staged file")
    originals = {p: (original / p).read_bytes() for p in goal.editable + goal.tests}
    recorded = report.get("acceptance_sha256")
    if not isinstance(recorded, dict) or any(agent_hash(originals[p]) != recorded.get(p)
                                                 for p in goal.tests):
        raise RepoStop("Previous acceptance test fingerprints changed")
    changes = {p: (stage / p).read_bytes() for p in changed_paths}
    # Re-validate stored model output before any use. No arbitrary paths.
    vetted = parse_edits(json.dumps({"edits": [
        {"path": p, "content": changes[p].decode("utf-8")} for p in changed_paths]}), goal)
    if vetted != changes or any(originals[p] == changes[p] for p in changed_paths):
        raise RepoStop("Previous candidate is missing or unchanged")
    expected_patch = create_diff(originals, changes)
    patch_file = dest / "changes.patch"
    if not patch_file.is_file() or patch_file.is_symlink() or patch_file.read_text() != expected_patch:
        raise RepoStop("Reviewed patch differs from approved bytes")
    preflight(dest)
    outcome = test_staged(stage, goal.tests, {p: agent_hash(originals[p]) for p in goal.tests})
    if not outcome["passed"]:
        raise RepoStop("Previously passing candidate failed re-verification; not applied")
    applied = apply_verified(goal, originals, changes, dest)
    report["applied"] = applied
    report["reverified_tests_run"] = outcome["tests_run"]
    atomic_report(dest, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("goal", type=Path, help="Absolute or relative JSON goal file")
    parser.add_argument("--execute", action="store_true", help="Generate and sandbox-test source in private staging")
    parser.add_argument("--apply", action="store_true", help="Update originals after success in this NEW run")
    parser.add_argument("--apply-verified", action="store_true", help="Apply a previous passing run without another model call")
    args = parser.parse_args()
    if args.apply and (not args.execute or args.apply_verified):
        parser.exit(2, "STOP: --apply requires --execute and cannot combine with --apply-verified\n")
    if args.apply_verified and args.execute:
        parser.exit(2, "STOP: --apply-verified cannot combine with --execute\n")
    try:
        data = json.loads(args.goal.read_text(encoding="utf-8"))
        goal = RepoGoal.parse(data)
        setup_runtime()
        if args.apply_verified:
            result = apply_previous(goal)
        else:
            result = asyncio.run(run(goal, apply=args.apply, plan_only=not args.execute))
        print(json.dumps({k: v for k, v in result.items() if k != "attempts"}, indent=2))
        if "attempts" in result:
            print(json.dumps({"attempts": result["attempts"]}, indent=2))
        if result.get("state") == "failed":
            raise RepoStop("No revision passed immutable acceptance tests")
    except (RepoStop, OSError, ValueError) as exc:
        parser.exit(1, f"STOP: {exc}\n")


if __name__ == "__main__":
    main()
