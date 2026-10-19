"""Detached private dashboard job: reuse v0.4E verification, never run shell tasks.

Only the API may launch this worker with a previously registered goal digest.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time

from mio.dashboard_jobs import _atomic_state, _directory, approved_goal
from mio.repo_agent import RepoStop
from scripts.native_runtime import setup_runtime
from scripts.repo_engineer import apply_previous, run


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[2] not in {"run", "apply"}:
        return 2
    identity, action = sys.argv[1:]
    setup_runtime()
    path = _directory("dashboard-jobs") / f"{identity}.{action}.json"
    started = int(time.time())
    result = {"id": identity, "action": action, "started_unix": started}
    try:
        goal, _ = approved_goal(identity)
        _atomic_state(path, {**result, "state": "running"})
        if action == "run":
            report = asyncio.run(run(goal, plan_only=False))
            state = "passed" if report.get("state") == "passed" else "failed"
        else:
            report = apply_previous(goal)
            state = "applied" if "applied" in report else "failed"
        print(json.dumps({"state": state, "tests_run": report.get("tests_run")}), flush=True)
        _atomic_state(path, {**result, "state": state, "completed_unix": int(time.time())})
        return 0 if state in {"passed", "applied"} else 1
    except (RepoStop, OSError, ValueError, RuntimeError) as exc:
        print(f"STOP: {type(exc).__name__}: {str(exc)[:300]}", flush=True)
        _atomic_state(path, {**result, "state": "stopped", "completed_unix": int(time.time()),
                             "error_type": type(exc).__name__})
        return 1


if __name__ == "__main__":
    sys.exit(main())
