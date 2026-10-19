"""Owner-registered repository jobs for the authenticated MioAgent dashboard.

No HTTP caller can register a repository, supply an arbitrary path or command,
select tests, or grant source-writing permissions. Registration is CLI-only.
The standard v0.4E engine remains the sole authority for test and apply gates.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from mio.repo_agent import RepoGoal, RepoStop, locked_snapshot, sha

RUNTIME = Path(f"/var/tmp/mioagent-native-{os.getuid()}")
IDENT = re.compile(r"[0-9a-f]{64}\Z")
LOCK = threading.Lock()
MAX_GOALS = 24
MAX_GOAL_SIZE = 16_000
RUN_STATUS = frozenset({"queued", "running", "passed", "failed", "stopped", "applied"})


def _private_dir(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) & 0o077 == 0


def _private_file(path: Path, limit: int = MAX_GOAL_SIZE) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) & 0o077 == 0 and info.st_size <= limit)


def _root() -> Path:
    if not _private_dir(RUNTIME):
        raise RepoStop("Private MioAgent runtime is unavailable")
    return RUNTIME


def _directory(name: str, *, create: bool = False) -> Path:
    directory = _root() / name
    if create and not directory.exists() and not directory.is_symlink():
        directory.mkdir(mode=0o700)
    if not _private_dir(directory):
        raise RepoStop("Private dashboard directory is unavailable")
    return directory


def _atomic_new(path: Path, data: dict) -> None:
    # Exclusive creation: a replay cannot replace an approved contract or job.
    raw = (json.dumps(data, sort_keys=True, indent=2) + "\n").encode()
    if len(raw) > MAX_GOAL_SIZE or path.is_symlink():
        raise RepoStop("Private record is invalid or exceeds its budget")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError as exc:
        raise RepoStop("Existing private record cannot be overwritten") from exc
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _atomic_state(path: Path, data: dict) -> None:
    # Runner updates only its own private job state, not the approved input.
    if not _private_file(path):
        raise RepoStop("Job state missing or unsafe")
    tmp = path.with_name(path.name + ".tmp")
    _atomic_new(tmp, data)
    os.replace(tmp, path)


def _read_json(path: Path, limit: int = MAX_GOAL_SIZE) -> dict:
    if not _private_file(path, limit):
        raise RepoStop("Private record not found or unsafe")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RepoStop("Invalid private record")
    return data


def register_goal(source: Path) -> dict:
    """Trusted local CLI registration, freezing the owner-selected test digests."""
    if not source.is_absolute() or not source.is_file() or source.is_symlink() or source.stat().st_size > MAX_GOAL_SIZE:
        raise RepoStop("Supply a regular absolute JSON goal under 16 KB")
    data = json.loads(source.read_text(encoding="utf-8"))
    goal = RepoGoal.parse(data)
    _, tests = locked_snapshot(goal)
    record = {"schema": 1, "id": goal.digest(), "goal": data,
              "selected_tests": {name: tests[name] for name in goal.tests},
              "registered_unix": int(time.time())}
    store = _directory("dashboard-approved-goals", create=True)
    if len(list(store.glob("*.json"))) >= MAX_GOALS:
        raise RepoStop("Registered dashboard goal limit reached")
    _atomic_new(store / f"{goal.digest()}.json", record)
    return {"id": goal.digest(), "repository": str(goal.root), "editable_files": list(goal.editable),
            "acceptance_tests": list(goal.tests)}


def approved_goal(identity: str) -> tuple[RepoGoal, dict]:
    if not IDENT.fullmatch(identity):
        raise RepoStop("Unknown dashboard goal")
    record = _read_json(_directory("dashboard-approved-goals") / f"{identity}.json")
    if record.get("schema") != 1 or record.get("id") != identity or not isinstance(record.get("goal"), dict):
        raise RepoStop("Registered goal has an invalid schema")
    goal = RepoGoal.parse(record["goal"])
    if goal.digest() != identity:
        raise RepoStop("Registered goal fingerprint differs")
    selected = record.get("selected_tests")
    if not isinstance(selected, dict) or set(selected) != set(goal.tests):
        raise RepoStop("Registered acceptance fingerprints missing")
    # Detect changes to trusted tests between registration and execution.
    for name in goal.tests:
        if not isinstance(selected[name], str) or len(selected[name]) != 64 or sha((goal.root / name).read_bytes()) != selected[name]:
            raise RepoStop("Trusted acceptance test changed since owner registration")
    return goal, record


def _read_job(identity: str, action: str) -> dict | None:
    if action not in {"run", "apply"}:
        raise RepoStop("Unsupported job action")
    try:
        record = _read_json(_directory("dashboard-jobs") / f"{identity}.{action}.json")
    except RepoStop:
        return None
    if (record.get("id") != identity or record.get("action") != action
            or record.get("state") not in RUN_STATUS):
        return None
    return {key: record.get(key) for key in ("id", "action", "state", "started_unix", "completed_unix", "error_type")}


def _report(identity: str) -> dict:
    report_path = _root() / "repo-engineering" / identity / "report.json"
    if not _private_dir(report_path.parent) or not _private_file(report_path, 150_000):
        return {}
    data = json.loads(report_path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) and data.get("goal_sha256") == identity else {}


def goal_info(identity: str) -> dict:
    goal, record = approved_goal(identity)
    report = _report(identity)
    return {"id": identity, "repository": str(goal.root), "task": goal.task,
            "editable_files": list(goal.editable), "acceptance_tests": list(goal.tests),
            "max_attempts": goal.max_attempts, "registered_unix": record["registered_unix"],
            "run": _read_job(identity, "run"), "apply": _read_job(identity, "apply"),
            "run_state": report.get("state"), "model": report.get("model"),
            "tests_run": report.get("tests_run", 0), "applied": "applied" in report,
            "patch_available": report.get("state") == "passed" and _private_file(
                _root() / "repo-engineering" / identity / "changes.patch", 150_000)}


def list_goals() -> list[dict]:
    try:
        directory = _directory("dashboard-approved-goals")
    except RepoStop:
        return []
    found = []
    for path in sorted(directory.iterdir()):
        if path.is_file() and IDENT.fullmatch(path.stem) and path.suffix == ".json":
            try:
                found.append(goal_info(path.stem))
            except (RepoStop, ValueError, OSError):
                continue
        if len(found) >= MAX_GOALS:
            break
    return found


def log_tail(identity: str, action: str) -> str:
    if not IDENT.fullmatch(identity) or action not in {"run", "apply"}:
        raise RepoStop("Unsupported job log")
    path = _directory("dashboard-jobs") / f"{identity}.{action}.log"
    if not _private_file(path, 2_000_000):
        return ""
    with path.open("rb") as f:
        f.seek(max(0, path.stat().st_size - 4_096))
        return f.read().decode("utf-8", errors="replace")[-3_000:]


def launch(identity: str, action: Literal["run", "apply"], patch_digest: str | None = None) -> dict:
    with LOCK:
        approved_goal(identity)
        jobs = _directory("dashboard-jobs", create=True)
        if any(p.suffix == ".json" and _private_file(p) and _read_json(p).get("state") in {"queued", "running"}
               for p in jobs.iterdir() if p.is_file() and not p.is_symlink()):
            raise RepoStop("A dashboard engineering job is already active")
        report = _report(identity)
        if action == "run":
            if report or (jobs / f"{identity}.run.json").exists():
                raise RepoStop("Goal already executed; register a new task for another run")
        else:
            if report.get("state") != "passed" or "applied" in report:
                raise RepoStop("Only a verified, unapplied run may be approved")
            patch_path = _root() / "repo-engineering" / identity / "changes.patch"
            if not _private_file(patch_path, 150_000) or patch_digest != hashlib.sha256(patch_path.read_bytes()).hexdigest():
                raise RepoStop("Patch changed or has not been reviewed")
        state_path = jobs / f"{identity}.{action}.json"
        log_path = jobs / f"{identity}.{action}.log"
        _atomic_new(state_path, {"id": identity, "action": action, "state": "queued",
                                 "started_unix": int(time.time())})
        logfd = os.open(log_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "scripts.dashboard_job_runner", identity, action],
                cwd=str(Path(__file__).resolve().parents[1]),
                stdin=subprocess.DEVNULL, stdout=logfd, stderr=subprocess.STDOUT,
                start_new_session=True, close_fds=True,
            )
        except OSError:
            _atomic_state(state_path, {"id": identity, "action": action, "state": "stopped",
                                       "started_unix": int(time.time()), "error_type": "StartFailed"})
            raise
        finally:
            os.close(logfd)
        # Reap in a daemon thread when API is alive; durable runner state survives restart.
        threading.Thread(target=proc.wait, daemon=True).start()
        return {"id": identity, "action": action, "state": "queued"}


class RunApproval(BaseModel):
    approved: Literal[True]


class ApplyApproval(BaseModel):
    approved: Literal[True]
    patch_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def register_job_routes(app: FastAPI, require_token) -> None:
    @app.get("/api/intelligence/goals", dependencies=[Depends(require_token)])
    def registered_goals() -> dict:
        return {"goals": list_goals()}

    @app.get("/api/intelligence/goals/{identity}/status", dependencies=[Depends(require_token)])
    def job_status(identity: str) -> dict:
        try:
            info = goal_info(identity)
            return {**info, "run_log": log_tail(identity, "run"), "apply_log": log_tail(identity, "apply")}
        except (RepoStop, OSError, ValueError) as exc:
            raise HTTPException(404, "Registered goal unavailable") from exc

    @app.post("/api/intelligence/goals/{identity}/start", status_code=202,
              dependencies=[Depends(require_token)])
    def start_job(identity: str, payload: RunApproval) -> dict:
        try:
            return launch(identity, "run")
        except (RepoStop, OSError, ValueError) as exc:
            raise HTTPException(409, str(exc)[:200]) from exc

    @app.post("/api/intelligence/goals/{identity}/apply", status_code=202,
              dependencies=[Depends(require_token)])
    def apply_job(identity: str, payload: ApplyApproval) -> dict:
        try:
            return launch(identity, "apply", payload.patch_sha256)
        except (RepoStop, OSError, ValueError) as exc:
            raise HTTPException(409, str(exc)[:200]) from exc
