"""Owner-controlled persistent engineering backlog; model proposals grant no permissions.

This is an orchestration *foundation*: a durable dependency plan with audit-friendly
model proposals, NOT an autonomous code executor or deployment mechanism.
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

SCHEMA = 1
ID = re.compile(r"[a-z][a-z0-9-]{2,47}\Z")
MAX_STORE = 150_000
PHASES = (
    ("ui-live", "Verify and deploy B2C1A Chat attachments and PNG downloads", (), "frontend", "Production Next.js build, authenticated upload, browser image download and rollback tested"),
    ("shared-web", "Add verified live research to Chat, Studio and Projects", ("ui-live",), "research", "Current webpage retrieved, cited and independently checked in each UI mode"),
    ("vision-edit", "Benchmark high-quality image models and implement true image editing", ("ui-live",), "image", "Reference edits preserve requested details; downloaded output and GPU limits verified"),
    ("asset-history", "Persist file, image and generated artifact links across modes", ("ui-live",), "documents", "File and image history survives browser refresh; deletion and authorization tested"),
    ("model-eval", "Benchmark installed local LLM roles with repeatable evaluation", (), "evaluation", "Model digests, quality, latency, failure modes and VRAM budgets recorded"),
    ("supervisor-jobs", "Implement durable multi-step approval-gated supervisor jobs", ("model-eval",), "planning", "Crash recovery, immutable plan, dependencies, budgets and per-step audit proven"),
    ("repo-runner", "Implement permission-scoped repository editing and repair loops", ("supervisor-jobs",), "coding", "Isolated repo tests, controlled diffs, iteration limits and safe rollback proven"),
    ("browser-tools", "Implement owner-authorized interactive browser capability", ("supervisor-jobs",), "research", "Domain-scoped browser, credential isolation and action auditing verified"),
    ("self-improve", "Propose, benchmark and review MioAgent self-improvements", ("repo-runner", "browser-tools", "shared-web"), "review", "Independent tests and quality gate before explicit owner-approved Git publication"),
)


def _task(row: tuple) -> dict:
    slug, title, deps, role, acceptance = row
    return {"id": slug, "title": title, "depends_on": list(deps), "role": role,
            "acceptance": acceptance, "state": "planned", "proposal": None,
            "verified_by_owner": False}


def initial_program(commit: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Invalid starting Git checkpoint")
    tasks = [_task(row) for row in PHASES]
    ids = {t["id"] for t in tasks}
    assert len(ids) == len(tasks)
    for task in tasks:
        assert all(d in ids and d != task["id"] for d in task["depends_on"])
    return {"schema": SCHEMA, "base_commit": commit, "created": int(time.time()),
            "tasks": tasks, "scope": "planning_only_no_automatic_execution"}


def path_for(uid: int | None = None) -> Path:
    return Path(f"/var/tmp/mioagent-native-{os.getuid() if uid is None else uid}/autonomy")


def _secure_directory(path: Path) -> None:
    if not path.is_absolute() or path.is_symlink():
        raise RuntimeError("Autonomy store must be an absolute non-symlink directory")
    parent = path.parent
    if not parent.is_dir() or parent.is_symlink():
        raise RuntimeError("Native runtime directory is unavailable")
    for check in (parent,):
        st = check.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise RuntimeError("Native runtime directory has insecure permissions")
    if not path.exists():
        path.mkdir(mode=0o700)
    st = path.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise RuntimeError("Autonomy store must be private and owner-managed")


def _check_file(path: Path) -> None:
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077 or st.st_size > MAX_STORE:
        raise RuntimeError("Unsafe or oversized autonomy state")


@contextmanager
def _locked(store: Path):
    _secure_directory(store)
    lock = store / "program.lock"
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        st = os.fstat(fd)
        if st.st_uid != os.getuid() or not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077:
            raise RuntimeError("Unsafe autonomy lock")
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _validate(data: dict) -> dict:
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or data.get("scope") != "planning_only_no_automatic_execution":
        raise RuntimeError("Unsupported autonomy state schema")
    tasks = data.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != len(PHASES):
        raise RuntimeError("Autonomy tasks do not match approved roadmap")
    expected = {entry[0] for entry in PHASES}
    ids = [task.get("id") for task in tasks if isinstance(task, dict)]
    if set(ids) != expected or len(ids) != len(expected):
        raise RuntimeError("Autonomy task identities differ from approved roadmap")
    for task in tasks:
        state = task.get("state")
        if state not in {"planned", "awaiting_review", "verified"}:
            raise RuntimeError("Unexpected autonomy task state")
        verification = task.get("verification")
        if state == "verified":
            if task.get("verified_by_owner") is not True or not isinstance(verification, dict):
                raise RuntimeError("Verified task lacks owner evidence")
            if set(verification) != {"summary", "artifact_sha256", "approved_at", "method"}:
                raise RuntimeError("Unexpected owner verification fields")
            if (not isinstance(verification["summary"], str)
                    or not 8 <= len(verification["summary"]) <= 600
                    or not isinstance(verification["artifact_sha256"], str)
                    or not re.fullmatch(r"[0-9a-f]{64}", verification["artifact_sha256"])
                    or not isinstance(verification["approved_at"], int)
                    or verification["approved_at"] < data["created"]
                    or verification["method"] != "explicit_owner_cli_v1"):
                raise RuntimeError("Invalid owner verification")
        elif task.get("verified_by_owner") is not False or verification is not None:
            raise RuntimeError("Unverified task contains an approval")
        if not isinstance(task.get("depends_on"), list) or task["depends_on"] != list(next(r[2] for r in PHASES if r[0] == task["id"])):
            raise RuntimeError("Autonomy dependencies were modified")
    completed = {t["id"] for t in tasks if t["state"] == "verified"}
    for task in tasks:
        if task["state"] == "verified" and not set(task["depends_on"]).issubset(completed):
            raise RuntimeError("Owner-verification dependency was not satisfied")
    return data


def _read(store: Path) -> dict:
    path = store / "program.json"
    _check_file(path)
    with path.open("rb") as handle:
        return _validate(json.loads(handle.read(MAX_STORE + 1)))


def _atomic(store: Path, obj: dict) -> None:
    raw = (json.dumps(obj, sort_keys=True, indent=2) + "\n").encode()
    if len(raw) > MAX_STORE:
        raise RuntimeError("Autonomy state exceeds byte limit")
    fd, name = tempfile.mkstemp(prefix=".program-", dir=store)
    try:
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, store / "program.json")
    finally:
        if os.path.exists(name):
            os.unlink(name)


def initialize(store: Path, commit: str) -> tuple[dict, bool]:
    with _locked(store):
        path = store / "program.json"
        if path.exists() or path.is_symlink():
            data = _read(store)
            if data["base_commit"] != commit:
                raise RuntimeError("Backlog already belongs to another Git baseline")
            return data, False
        data = initial_program(commit)
        _atomic(store, data)
        return data, True


def read_program(store: Path) -> dict:
    with _locked(store):
        return _read(store)


def ready_tasks(program: dict) -> list[dict]:
    data = _validate(program)
    completed = {t["id"] for t in data["tasks"] if t["verified_by_owner"]}
    return [t for t in data["tasks"] if t["state"] == "planned" and set(t["depends_on"]).issubset(completed)]


def parse_proposal(text: str) -> list[str]:
    if not isinstance(text, str) or len(text) > 14_000:
        raise ValueError("Invalid model plan length")
    cleaned = text.strip()
    if cleaned.startswith("```json") and cleaned.endswith("```"):
        cleaned = cleaned[7:-3].strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError("Model plan is not valid JSON") from exc
    if not isinstance(data, dict) or set(data) != {"steps"}:
        raise ValueError("Model plan must contain only a steps field")
    steps = data["steps"]
    if not isinstance(steps, list) or not 3 <= len(steps) <= 7 or any(
        not isinstance(x, str) or not 8 <= len(x.strip()) <= 280 for x in steps
    ):
        raise ValueError("Model plan requires three to seven bounded steps")
    return [x.strip() for x in steps]


def save_proposal(store: Path, task_id: str, steps: list[str], model: str) -> dict:
    if not ID.fullmatch(task_id) or not isinstance(model, str) or not 1 <= len(model) <= 95:
        raise ValueError("Invalid task or model identity")
    normalized = parse_proposal(json.dumps({"steps": steps}))
    with _locked(store):
        data = _read(store)
        eligible = {task["id"] for task in ready_tasks(data)}
        if task_id not in eligible:
            raise RuntimeError("Task is blocked or already planned; no proposal stored")
        item = next(x for x in data["tasks"] if x["id"] == task_id)
        serialized = json.dumps(normalized, separators=(",", ":"))
        item["proposal"] = {"steps": normalized, "model": model,
                            "sha256": hashlib.sha256(serialized.encode()).hexdigest(),
                            "created": int(time.time()), "status": "untrusted_model_proposal"}
        item["state"] = "awaiting_review"
        _atomic(store, data)
        return item


def verify_task(store: Path, task_id: str, artifact_sha256: str, summary: str, *,
                owner_confirmed: bool = False) -> dict:
    """Explicit workstation-owner approval; NOT proof of automated acceptance.

    The owner must inspect the required acceptance criteria and submit evidence.
    We verify the evaluator report bytes for model-eval; other tasks remain owner
    attestations until independent acceptance adapters are implemented.
    """
    if not owner_confirmed:
        raise ValueError("Explicit owner confirmation is required")
    if not isinstance(task_id, str) or not ID.fullmatch(task_id):
        raise ValueError("Invalid task identifier")
    if not isinstance(artifact_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", artifact_sha256):
        raise ValueError("Provide a SHA256 fingerprint of the reviewed evidence")
    if not isinstance(summary, str) or not 8 <= len(summary.strip()) <= 600:
        raise ValueError("Provide a bounded owner review summary")
    if task_id == "model-eval":
        path = store / "reports" / (artifact_sha256 + ".json")
        _check_file(path)
        contents = path.read_bytes()
        if hashlib.sha256(contents).hexdigest() != artifact_sha256:
            raise RuntimeError("Model evaluation evidence checksum mismatch")
        report = json.loads(contents)
        results = report.get("results") if isinstance(report, dict) else None
        models = report.get("models") if isinstance(report, dict) else None
        if (not isinstance(report, dict) or report.get("schema") != 1
                or report.get("cloud_calls") is not False
                or report.get("model_downloads") is not False
                or report.get("role_policy_modified") is not False
                or not isinstance(models, list) or len(models) != 3
                or not all(isinstance(m, dict) and isinstance(m.get("name"), str)
                           and isinstance(m.get("digest"), str)
                           and re.fullmatch(r"[0-9a-f]{12,64}", m["digest"]) for m in models)
                or len({m["name"] for m in models}) != 3
                or not isinstance(results, list) or len(results) != 12
                or not all(isinstance(x, dict) and isinstance(x.get("passed"), bool)
                           for x in results)):
            raise RuntimeError("Evidence does not contain a valid local model evaluation")
        expected = {(m["name"], role) for m in models
                    for role in ("planning", "coding", "writing", "research")}
        if {(x.get("model"), x.get("role")) for x in results} != expected:
            raise RuntimeError("Model evaluation role coverage is incomplete")
    with _locked(store):
        data = _read(store)
        item = next((t for t in data["tasks"] if t["id"] == task_id), None)
        if item is None or item["state"] == "verified":
            raise RuntimeError("Unknown or already verified milestone")
        completed = {t["id"] for t in data["tasks"] if t["verified_by_owner"]}
        if not set(item["depends_on"]).issubset(completed):
            raise RuntimeError("Cannot approve a milestone before its dependencies")
        item["state"] = "verified"
        item["verified_by_owner"] = True
        item["verification"] = {"summary": summary.strip(),
                                "artifact_sha256": artifact_sha256,
                                "approved_at": int(time.time()),
                                "method": "explicit_owner_cli_v1"}
        _validate(data)
        _atomic(store, data)
        return item
