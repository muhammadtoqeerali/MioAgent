"""AUT3B: owner-approved supervisor step -> sandbox-only repository proposal.

No arbitrary tool grants, shell commands, repository writes, downloads, or Git
publication. Existing repo_engineer.run provides bounded, trusted test execution.
This bridge refuses retries after an interrupted run until separately reviewed.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from mio.autonomy_program import _secure_directory, read_program
from mio.autonomy_supervisor import begin_step, complete_step, read_jobs, reconcile_interrupted

HEX32 = re.compile(r"[0-9a-f]{32}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
SUPPORTED_TASKS = frozenset({"repo-runner", "self-improve"})
MAX_EVIDENCE = 150_000


def _regular_private(path: Path, max_bytes: int = MAX_EVIDENCE) -> bytes:
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077 or not 1 <= info.st_size <= max_bytes):
        raise RuntimeError("Evidence is not a bounded owner-private regular file")
    return path.read_bytes()


def _goal(goal_id: str):
    if not isinstance(goal_id, str) or not HEX64.fullmatch(goal_id):
        raise ValueError("Owner-registered goal SHA256 required")
    from mio.dashboard_jobs import approved_goal  # Import only after checking ID

    goal, record = approved_goal(goal_id)
    if goal.digest() != goal_id or record.get("id") != goal_id:
        raise RuntimeError("Registered repository goal fingerprint mismatch")
    return goal


def inspect_binding(store: Path, job_id: str, index: int, goal_id: str,
                    plan_sha256: str) -> dict[str, Any]:
    """Read-only eligibility check; untrusted plan text cannot authorize tools."""
    if (not isinstance(job_id, str) or not HEX32.fullmatch(job_id)
            or not isinstance(plan_sha256, str) or not HEX64.fullmatch(plan_sha256)
            or type(index) is not int or not 0 <= index <= 6):
        raise ValueError("Job, plan digest, or step index invalid")
    program = read_program(store)
    jobs = read_jobs(store)
    job = next((item for item in jobs if item["id"] == job_id), None)
    if job is None or job["state"] != "approved" or job["plan_sha256"] != plan_sha256:
        raise RuntimeError("Job must have a matching frozen, owner-approved plan")
    if job["task"] not in SUPPORTED_TASKS:
        raise RuntimeError("Supervisor task has no repository-editing capability")
    task = next((item for item in program["tasks"] if item["id"] == job["task"]), None)
    completed = {item["id"] for item in program["tasks"] if item["verified_by_owner"]}
    if (task is None or task["acceptance"] != job["acceptance"]
            or not set(task["depends_on"]).issubset(completed)):
        raise RuntimeError("Task snapshot or prerequisite verification differs")
    if index >= len(job["steps"]) or job["steps"][index]["state"] != "pending":
        raise RuntimeError("Step is not pending")
    if any(step["state"] != "verified" for step in job["steps"][:index]):
        raise RuntimeError("Earlier supervisor steps have not been verified")
    if any(other["state"] == "running" for other in jobs):
        raise RuntimeError("Another supervisor job is already running")
    goal = _goal(goal_id)
    return {"job": job_id, "task": job["task"], "index": index,
            "plan_sha256": plan_sha256, "goal_sha256": goal_id,
            "repository": str(goal.root), "editable_files": list(goal.editable),
            "acceptance_tests": list(goal.tests), "max_attempts": goal.max_attempts,
            "proposed_step": job["steps"][index]["text"],
            "capability": "private_python_patch_and_bubblewrap_tests_only"}


@contextmanager
def _execution_lock(store: Path):
    _secure_directory(store)
    path = store / "aut3b.lock"
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077):
            raise RuntimeError("Untrusted AUT3B execution lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("A supervisor engineering execution is already active") from exc
        yield
    finally:
        os.close(fd)


def _record_path(store: Path, job_id: str, index: int, goal_id: str) -> Path:
    return store / f"aut3b-{job_id}-{index}-{goal_id}.json"


def _write_record(path: Path, payload: dict, *, create: bool) -> None:
    raw = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode()
    if len(raw) > 10_000:
        raise RuntimeError("AUT3B run record exceeded limit")
    if create:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        return
    _regular_private(path, 10_000)
    fd, temp = tempfile.mkstemp(prefix=".aut3b-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def verified_patch_evidence(folder: Path, goal_id: str, report: dict) -> dict:
    """Require stored repo-engineer evidence, not its in-memory success claim alone."""
    if (report.get("state") != "passed" or report.get("goal_sha256") != goal_id
            or type(report.get("tests_run")) is not int or report["tests_run"] < 1
            or "applied" in report):
        raise RuntimeError("Repository run did not pass trusted tests without applying edits")
    if folder.is_symlink() or not folder.is_dir():
        raise RuntimeError("Private repository artifact folder missing")
    report_bytes = _regular_private(folder / "report.json")
    patch_bytes = _regular_private(folder / "changes.patch")
    stored = json.loads(report_bytes)
    if (not isinstance(stored, dict) or stored != report
            or stored.get("state") != "passed"
            or stored.get("goal_sha256") != goal_id
            or stored.get("patch") != str(folder / "changes.patch")):
        raise RuntimeError("Stored engineering evidence differs from returned result")
    attempts = stored.get("attempts")
    if (not isinstance(attempts, list) or not attempts
            or attempts[-1].get("outcome") != "passed"
            or not isinstance(attempts[-1].get("changed_files"), list)
            or not attempts[-1]["changed_files"]):
        raise RuntimeError("No passing source-change attempt recorded")
    return {"report_sha256": hashlib.sha256(report_bytes).hexdigest(),
            "patch_sha256": hashlib.sha256(patch_bytes).hexdigest(),
            "tests_run": report["tests_run"], "attempts": len(attempts),
            "changed_files": attempts[-1]["changed_files"]}


async def run_approved_step(store: Path, job_id: str, index: int, goal_id: str,
                            plan_sha256: str, *, owner_confirmed: bool = False) -> dict:
    """Execute bounded repository inference/tests. NEVER call apply or Git."""
    if owner_confirmed is not True:
        raise ValueError("Explicit owner approval of this exact engineering step required")
    with _execution_lock(store):
        preview = inspect_binding(store, job_id, index, goal_id, plan_sha256)
        goal = _goal(goal_id)
        # registered goal verifies frozen acceptance test bytes again
        path = _record_path(store, job_id, index, goal_id)
        if path.exists() or path.is_symlink():
            raise RuntimeError("Engineering step already attempted; inspect record and reconcile")
        from scripts.native_runtime import RUNTIME
        from scripts.repo_engineer import run as repo_run

        folder = RUNTIME / "repo-engineering" / goal_id
        if folder.exists() or folder.is_symlink():
            raise RuntimeError("Repository goal was already executed; a fresh goal is required")
        started = {"schema": 1, "state": "started", "created": int(time.time()),
                   "binding": preview, "source_applied": False, "git_published": False}
        # Begin and durably record before any model invocation. Crash -> reconcile.
        begin_step(store, job_id, index)
        _write_record(path, started, create=True)
        try:
            report = await repo_run(goal, apply=False, plan_only=False)
            evidence = verified_patch_evidence(folder, goal_id, report)
            result = {**started, "state": "needs_owner_review", "evidence": evidence,
                      "finished": int(time.time()), "source_applied": False,
                      "git_published": False}
            _write_record(path, result, create=False)
            # Supervisor records test-backed evidence but still requires final review.
            step = complete_step(store, job_id, index, evidence["report_sha256"])
            return {"state": "needs_owner_review", "job_state": step["state"],
                    "record": str(path), **evidence, "source_applied": False,
                    "git_published": False}
        except Exception as exc:
            failure = {**started, "state": "interrupted", "failure_type": type(exc).__name__,
                       "finished": int(time.time())}
            try:
                _write_record(path, failure, create=False)
            finally:
                # Keep step pending for explicit owner resume, not silently complete.
                reconcile_interrupted(store)
            raise
