"""SCORPIO9C6: explicit-owner synthetic live Work canary, never automatic.

The release controller must never call prepare_canary(). Production writes require
an interactive owner terminal and a second, independent Supervisor UI approval.
No API, model, background worker or remotely supplied path can issue approval.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import stat
import time
from contextlib import closing
from pathlib import Path

from mio.scorpio9c3_step_grants import expected_prompt, stage
from mio.scorpio9c_observe import _readonly_db, _table
from mio.scorpio9c_tools import _private_directory, input_directory
from mio.supervisor_core import create_plan
from mio.work_core import MAX_PROJECTS, RUNTIME, WorkStop, _id, create_project

CANARY_TITLE = "SCORPIO9C6 Synthetic Owner Canary"
CANARY_MARKER = "SCORPIO9C6 OWNER CANARY ONLY - SYNTHETIC DATA - EXPLICIT REVIEW REQUIRED"
CANARY_FILE = "scorpio9c6_canary.txt"
CANARY_BYTES = b"MioAgent Scorpio9C6 synthetic owner-approved digest canary\n"
CANARY_SHA256 = hashlib.sha256(CANARY_BYTES).hexdigest()
APPROVAL = "APPROVE SCORPIO9C6 CREATE SYNTHETIC LIVE DRAFT NO AUTO APPROVAL"


def _count(conn: sqlite3.Connection, table: str, where: str = "1=1") -> int:
    if not _table(conn, table):
        return 0
    # Only static strings from this module; never user input or dynamic SQL identifiers.
    return int(conn.execute(f"SELECT count(*) FROM {table} WHERE {where}").fetchone()[0])


def readiness(root: Path = RUNTIME / "work") -> dict:
    """Read-only production-safe preflight; missing Work DB is a denial."""
    with closing(_readonly_db(root)) as conn:
        if not _table(conn, "projects") or not _table(conn, "runs"):
            raise WorkStop("Existing Work schema unavailable")
        projects = _count(conn, "projects")
        active_runs = _count(conn, "runs", "state IN ('queued','running')")
        active_plans = _count(conn, "supervisor_plans", "state IN ('ready','running')")
        canaries = int(conn.execute(
            "SELECT count(*) FROM projects WHERE title=? AND instructions=?",
            (CANARY_TITLE, CANARY_MARKER),
        ).fetchone()[0])
        ready = (active_runs == 0 and active_plans == 0 and canaries == 0
                 and projects < MAX_PROJECTS and _count(conn, "supervisor_plans") < 100)
        return {
            "release": "SCORPIO9C6",
            "read_only": True,
            "existing_projects": projects,
            "active_work_runs": active_runs,
            "active_supervisor_plans": active_plans,
            "existing_canaries": canaries,
            "eligible_for_separate_owner_canary": ready,
            "production_data_modified": False,
        }


def _backup(root: Path) -> Path:
    """Consistent private SQLite backup BEFORE any canary writes."""
    parent = root.parent
    _private_directory(parent)
    folder = parent / "scorpio9c6-canary-backups"
    if not folder.exists() and not folder.is_symlink():
        folder.mkdir(mode=0o700)
    _private_directory(folder)
    target = folder / ("work-before-canary-" + secrets.token_hex(12) + ".sqlite3")
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    os.close(fd)
    try:
        with (
            closing(_readonly_db(root)) as source,
            closing(sqlite3.connect(str(target))) as destination,
        ):
            source.backup(destination)
        info = target.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size == 0):
            raise WorkStop("Backup verification failed")
        return target
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def _make_synthetic_file(root: Path, project_id: str) -> None:
    """Never accept a caller-supplied host path or read a real user file."""
    parent = root.parent
    _private_directory(parent)
    base = parent / "tool-inputs"
    if not base.exists() and not base.is_symlink():
        base.mkdir(mode=0o700)
    _private_directory(base)
    folder = base / project_id
    folder.mkdir(mode=0o700)
    _private_directory(folder)
    if input_directory(root, project_id) != folder:
        raise WorkStop("Canary input folder scope mismatch")
    path = folder / CANARY_FILE
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb", closefd=True) as out:
        out.write(CANARY_BYTES)
        out.flush()
        os.fsync(out.fileno())


def _prepare_canary(root: Path) -> dict:
    """Internal testable implementation; not exposed through an HTTP route."""
    check = readiness(root)
    if not check["eligible_for_separate_owner_canary"]:
        raise WorkStop("Existing Work activity, resource capacity or a prior canary blocks preparation")
    backup = _backup(root)
    # Intentionally no auto-rollback of production: never risk clobbering
    # concurrent legitimate Work changes. An interrupted partial draft remains
    # labeled for owner review and retries are refused by readiness().
    project = create_project(root, CANARY_TITLE, CANARY_MARKER)
    _make_synthetic_file(root, project["id"])
    plan = create_plan(root, project["id"],
                       "Verify one synthetic owner-approved offline digest canary",
                       [expected_prompt(CANARY_FILE)])
    step = plan["steps"][0]
    grant = stage(root, project["id"], plan["id"], step["id"],
                  CANARY_FILE, minutes=30)
    return {
        "status": "draft_waiting_independent_owner_approval",
        "project_id": project["id"],
        "plan_id": plan["id"],
        "step_id": step["id"],
        "grant_id": grant["grant_id"],
        "grant_expires": grant["expires"],
        "synthetic_sha256": CANARY_SHA256,
        "backup": str(backup),
        "automatic_approval": False,
        "worker_started_by_canary": False,
    }


def prepare_canary(root: Path = RUNTIME / "work") -> dict:
    if Path(root) != RUNTIME / "work":
        raise WorkStop("Production canary must target the fixed native Work root")
    if not os.isatty(0) or not os.isatty(1):
        raise WorkStop("Interactive local owner terminal required")
    return _prepare_canary(root)


def verify_canary(project_id: str, plan_id: str, root: Path = RUNTIME / "work") -> dict:
    """Read-only trace of explicit owner plan through the persistent Work worker."""
    project_id = _id(project_id)
    plan_id = _id(plan_id)
    with closing(_readonly_db(root)) as conn:
        if not _table(conn, "scorpio9c_step_bindings"):
            raise WorkStop("Staged-grant table absent; no completed canary")
        project = conn.execute(
            "SELECT title,instructions FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        if (project is None or project["title"] != CANARY_TITLE
                or project["instructions"] != CANARY_MARKER):
            raise WorkStop("Not the labeled synthetic owner canary")
        plan = conn.execute(
            "SELECT state FROM supervisor_plans WHERE id=? AND project=?",
            (plan_id, project_id),
        ).fetchone()
        if plan is None:
            raise WorkStop("Canary plan/project mismatch")
        steps = conn.execute(
            "SELECT id,prompt,state,run_id FROM supervisor_steps WHERE plan=?",
            (plan_id,),
        ).fetchall()
        if len(steps) != 1 or steps[0]["prompt"] != expected_prompt(CANARY_FILE):
            raise WorkStop("Canary step was altered")
        step = steps[0]
        binding = conn.execute(
            "SELECT b.grant_id,g.used,g.revoked,g.expires,g.owner_uid,g.tool,"
            "g.file_name,g.project,g.plan FROM scorpio9c_step_bindings b "
            "JOIN scorpio9c_grants g ON g.id=b.grant_id "
            "WHERE b.step=? AND b.project=? AND b.plan=?",
            (step["id"], project_id, plan_id),
        ).fetchone()
        if (binding is None or binding["owner_uid"] != os.getuid()
                or binding["file_name"] != CANARY_FILE
                or binding["project"] != project_id or binding["plan"] != plan_id
                or binding["tool"] != "workspace.sha256.v1"):
            raise WorkStop("Canary grant binding mismatch")
        run = None
        run_events: list[str] = []
        if step["run_id"]:
            run = conn.execute(
                "SELECT state,mode,result,prompt,project FROM runs WHERE id=?",
                (step["run_id"],),
            ).fetchone()
            if run is None or run["project"] != project_id or run["prompt"] != step["prompt"]:
                raise WorkStop("Canary run identity mismatch")
            run_events = [r[0] for r in conn.execute(
                "SELECT phase FROM events WHERE run=? ORDER BY id", (step["run_id"],)
            )]
        grant_events = [r[0] for r in conn.execute(
            "SELECT kind FROM scorpio9c_events WHERE grant_id=? ORDER BY id",
            (binding["grant_id"],),
        )]
        state = plan["state"]
        outcome = "waiting_for_owner_approval" if state == "draft" else "pending_worker_or_review"
        if state == "attention":
            outcome = "denied_owner_review_required"
        elif state == "complete":
            if (step["state"] != "done" or run is None or run["state"] != "answered"
                    or run["mode"] != "tool_sha256"
                    or run["result"] != "Verified offline SHA-256: " + CANARY_SHA256
                    or binding["used"] != 1 or binding["revoked"]
                    or run_events.count("tool.claimed") != 1
                    or run_events.count("tool.verified") != 1
                    or grant_events.count("consumed.worker.step_bound") != 1
                    or grant_events.count("sandbox.sha256.worker.success") != 1):
                raise WorkStop("Completed canary lacks exact execution and audit evidence")
            outcome = "passed_real_managed_worker"
        return {
            "release": "SCORPIO9C6",
            "outcome": outcome,
            "plan_state": state,
            "step_state": step["state"],
            "run_state": run["state"] if run is not None else None,
            "grant_consumed": bool(binding["used"]),
            "grant_revoked": bool(binding["revoked"]),
            "grant_expired": binding["expires"] <= int(time.time()),
            "run_claim_events": run_events.count("tool.claimed"),
            "run_verified_events": run_events.count("tool.verified"),
            "read_only": True,
        }
