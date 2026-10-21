"""Durable owner-gated supervisor jobs: plans, audit and crash recovery, no execution.

A job is a frozen, untrusted planning proposal. These functions NEVER run shell,
edit source, grant browser/network rights, change model policy or publish Git.
Only the workstation owner's explicit CLI can approve or record a verified step.
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
import uuid
from contextlib import contextmanager
from pathlib import Path

from mio.autonomy_program import _secure_directory, parse_proposal, read_program

MAX_JOBS = 30
MAX_EVENTS = 250
MAX_BYTES = 200_000
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
JOB_ID = re.compile(r"[0-9a-f]{32}\Z")


def plan_digest(steps: list[str]) -> str:
    validated = parse_proposal(json.dumps({"steps": steps}))
    return hashlib.sha256(json.dumps(validated, separators=(",", ":")).encode()).hexdigest()


@contextmanager
def _locked(store: Path):
    _secure_directory(store)
    path = store / "supervisor.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise RuntimeError("Untrusted supervisor lock")
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _check(data: dict) -> dict:
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise RuntimeError("Unsupported supervisor state")
    jobs = data.get("jobs")
    if not isinstance(jobs, list) or len(jobs) > MAX_JOBS:
        raise RuntimeError("Invalid supervisor job count")
    ids = set()
    for job in jobs:
        if not isinstance(job, dict) or not isinstance(job.get("id"), str):
            raise TypeError("Malformed supervisor job")
        if not JOB_ID.fullmatch(job["id"]) or job["id"] in ids:
            raise RuntimeError("Duplicate or malformed supervisor ID")
        ids.add(job["id"])
        if job.get("state") not in {"awaiting_approval", "approved", "running", "interrupted", "needs_review", "completed"}:
            raise RuntimeError("Unknown supervisor state")
        steps = job.get("steps")
        if not isinstance(steps, list) or not 3 <= len(steps) <= 7:
            raise RuntimeError("Malformed supervisor steps")
        if plan_digest([s["text"] for s in steps]) != job.get("plan_sha256"):
            raise RuntimeError("Supervisor plan integrity check failed")
        for index, step in enumerate(steps):
            if step.get("index") != index or step.get("state") not in {"pending", "in_progress", "verified"}:
                raise RuntimeError("Malformed supervisor step")
            evidence = step.get("evidence_sha256")
            if (step["state"] == "verified") != (isinstance(evidence, str) and bool(DIGEST.fullmatch(evidence))):
                raise RuntimeError("Supervisor step evidence integrity check failed")
        if sum(s["state"] == "in_progress" for s in steps) > 1:
            raise RuntimeError("Multiple steps are in progress")
        if job["state"] == "running" and not any(s["state"] == "in_progress" for s in steps):
            raise RuntimeError("Running supervisor job lacks an active step")
        if job["state"] == "completed" and not all(s["state"] == "verified" for s in steps):
            raise RuntimeError("Completed job has unfinished steps")
        events = job.get("events")
        if not isinstance(events, list) or len(events) > MAX_EVENTS:
            raise RuntimeError("Supervisor audit trail malformed")
        if not isinstance(job.get("task"), str) or not isinstance(job.get("acceptance"), str):
            raise TypeError("Supervisor task snapshot invalid")
    return data


def _load(store: Path) -> dict:
    path = store / "supervisor.json"
    if not path.exists() and not path.is_symlink():
        return {"schema": 1, "jobs": []}
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > MAX_BYTES:
        raise RuntimeError("Supervisor ledger must be private and bounded")
    return _check(json.loads(path.read_bytes()))


def _save(store: Path, data: dict) -> None:
    raw = (json.dumps(_check(data), sort_keys=True, indent=2) + "\n").encode()
    if len(raw) > MAX_BYTES:
        raise RuntimeError("Supervisor ledger exceeds storage budget")
    fd, temporary = tempfile.mkstemp(prefix=".supervisor-", dir=store)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, store / "supervisor.json")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _audit(job: dict, action: str, note: str = "") -> None:
    if len(job["events"]) >= MAX_EVENTS:
        raise RuntimeError("Supervisor audit budget exhausted")
    job["events"].append({"sequence": len(job["events"]) + 1, "at": int(time.time()),
                          "action": action, "note": note[:150]})


def read_jobs(store: Path) -> list[dict]:
    with _locked(store):
        return _load(store)["jobs"]


def create_job(store: Path, task_id: str) -> dict:
    program = read_program(store)
    item = next((t for t in program["tasks"] if t["id"] == task_id), None)
    completed = {t["id"] for t in program["tasks"] if t["verified_by_owner"]}
    if item is None or item["state"] != "awaiting_review" or not set(item["depends_on"]).issubset(completed):
        raise RuntimeError("Task requires an eligible, existing planning proposal")
    proposal = item.get("proposal")
    if not isinstance(proposal, dict) or proposal.get("status") != "untrusted_model_proposal":
        raise RuntimeError("Missing validated model planning proposal")
    steps = parse_proposal(json.dumps({"steps": proposal.get("steps")}))
    digest = plan_digest(steps)
    if digest != proposal.get("sha256"):
        raise RuntimeError("Model plan has been changed")
    with _locked(store):
        data = _load(store)
        if len(data["jobs"]) >= MAX_JOBS or any(j["task"] == task_id for j in data["jobs"]):
            raise RuntimeError("Supervisor job already exists or capacity reached")
        job = {"id": uuid.uuid4().hex, "task": task_id, "acceptance": item["acceptance"],
               "plan_sha256": digest, "model": proposal["model"],
               "state": "awaiting_approval", "created": int(time.time()),
               "steps": [{"index": i, "text": step, "state": "pending", "evidence_sha256": None}
                         for i, step in enumerate(steps)], "events": []}
        _audit(job, "created", "Model plan is untrusted and cannot execute actions")
        data["jobs"].append(job)
        _save(store, data)
        return job


def _job(data: dict, job_id: str) -> dict:
    if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
        raise ValueError("Invalid job ID")
    job = next((j for j in data["jobs"] if j["id"] == job_id), None)
    if job is None:
        raise RuntimeError("Unknown supervisor job")
    return job


def approve_job(store: Path, job_id: str, expected_sha256: str, *, owner_confirmed: bool = False) -> dict:
    if not owner_confirmed or not isinstance(expected_sha256, str) or not DIGEST.fullmatch(expected_sha256):
        raise ValueError("Explicit owner approval and frozen plan digest required")
    with _locked(store):
        data = _load(store)
        job = _job(data, job_id)
        if job["state"] != "awaiting_approval" or job["plan_sha256"] != expected_sha256:
            raise RuntimeError("Supervisor approval does not match the unmodified plan")
        job["state"] = "approved"
        _audit(job, "owner_approved", "Planning steps only, no execution grant")
        _save(store, data)
        return job


def begin_step(store: Path, job_id: str, index: int) -> dict:
    with _locked(store):
        data = _load(store)
        job = _job(data, job_id)
        if job["state"] != "approved" or not isinstance(index, int) or not 0 <= index < len(job["steps"]):
            raise RuntimeError("Step is not eligible to begin")
        if any(s["state"] == "in_progress" for s in job["steps"]):
            raise RuntimeError("Another step is already in progress")
        if any(s["state"] != "verified" for s in job["steps"][:index]):
            raise RuntimeError("Earlier steps need owner-verification evidence")
        step = job["steps"][index]
        if step["state"] != "pending":
            raise RuntimeError("Step is already recorded")
        step["state"] = "in_progress"
        job["state"] = "running"
        _audit(job, "step_started", str(index))
        _save(store, data)
        return job


def complete_step(store: Path, job_id: str, index: int, evidence_sha256: str) -> dict:
    if not isinstance(evidence_sha256, str) or not DIGEST.fullmatch(evidence_sha256):
        raise ValueError("Immutable SHA256 evidence is required")
    with _locked(store):
        data = _load(store)
        job = _job(data, job_id)
        if (job["state"] != "running" or not isinstance(index, int)
                or not 0 <= index < len(job["steps"])
                or job["steps"][index]["state"] != "in_progress"):
            raise RuntimeError("No matching step is running")
        job["steps"][index].update({"state": "verified", "evidence_sha256": evidence_sha256})
        job["state"] = "needs_review" if all(s["state"] == "verified" for s in job["steps"]) else "approved"
        _audit(job, "step_evidence_recorded", str(index))
        _save(store, data)
        return job


def reconcile_interrupted(store: Path) -> int:
    """Explicit restart reconciliation: record running steps as interrupted; never completed."""
    with _locked(store):
        data = _load(store)
        count = 0
        for job in data["jobs"]:
            if job["state"] == "running":
                job["state"] = "interrupted"
                for step in job["steps"]:
                    if step["state"] == "in_progress":
                        step["state"] = "pending"
                _audit(job, "interrupted", "Unfinished work needs fresh owner approval")
                count += 1
        if count:
            _save(store, data)
        return count


def resume_job(store: Path, job_id: str, *, owner_confirmed: bool = False) -> dict:
    if not owner_confirmed:
        raise ValueError("Owner must explicitly approve an interrupted job")
    with _locked(store):
        data = _load(store)
        job = _job(data, job_id)
        if job["state"] != "interrupted":
            raise RuntimeError("Only interrupted jobs can be resumed")
        job["state"] = "approved"
        _audit(job, "owner_resumed", "Remaining steps require new acceptance evidence")
        _save(store, data)
        return job


def finalize_job(store: Path, job_id: str, *, owner_confirmed: bool = False) -> dict:
    if not owner_confirmed:
        raise ValueError("Owner must approve final verification")
    program = read_program(store)
    with _locked(store):
        data = _load(store)
        job = _job(data, job_id)
        item = next((t for t in program["tasks"] if t["id"] == job["task"]), None)
        if (job["state"] != "needs_review" or item is None
                or item["state"] != "verified" or not item["verified_by_owner"]):
            raise RuntimeError("All steps and owner milestone verification must pass first")
        job["state"] = "completed"
        _audit(job, "owner_finalized", "No autonomous deployment or repository write")
        _save(store, data)
        return job
