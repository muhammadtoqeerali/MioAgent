"""SCORPIO9C3: owner-staged, exact-step capability grants with no worker hook.

An owner may stage an offline digest grant for a DRAFT supervisor step. The
existing SCORPIO9C1 executor continues to deny use until the plan is approved;
this module does not grant any automatic worker or API permission.
"""
from __future__ import annotations

import os
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path

from mio.scorpio9c_observe import _readonly_db, _table
from mio.scorpio9c_tools import TOOL_ID, _digest, _open_input, _schema_tools
from mio.supervisor_core import _schema
from mio.work_core import WorkStop, _id, db

MAX_STAGED = 1000


def expected_prompt(name: str) -> str:
    return f"Compute SHA-256 for owner-approved file: {name}"


def _bindings_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scorpio9c_step_bindings (
          step TEXT PRIMARY KEY REFERENCES supervisor_steps(id) ON DELETE CASCADE,
          grant_id TEXT NOT NULL UNIQUE REFERENCES scorpio9c_grants(id) ON DELETE CASCADE,
          project TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          plan TEXT NOT NULL REFERENCES supervisor_plans(id) ON DELETE CASCADE,
          created INTEGER NOT NULL
        )
    """)


def stage(root: Path, project_id: str, plan_id: str, step_id: str,
          file_name: str, *, minutes: int = 15) -> dict:
    """Stage only from interactive owner terminal; no HTTP/model call sites."""
    if not os.isatty(0):
        raise WorkStop("Staging requires the interactive owner terminal")
    return _stage(root, project_id, plan_id, step_id, file_name, minutes=minutes)


def _stage(root: Path, project_id: str, plan_id: str, step_id: str,
           file_name: str, *, minutes: int = 15) -> dict:
    """Deterministic implementation for private, isolated security tests.

    The plan MUST be draft; the worker cannot queue any draft step. The owner
    must later approve the plan using the existing independent approval path.
    """
    for item in (project_id, plan_id, step_id):
        _id(item)
    if type(minutes) is not int or not 1 <= minutes <= 30:
        raise WorkStop("Grant duration must be 1 to 30 minutes")
    fd, info, folder = _open_input(root, project_id, file_name)
    try:
        sha = _digest(fd)
        after = os.fstat(fd)
        if (after.st_dev, after.st_ino, after.st_size) != (info.st_dev, info.st_ino, info.st_size):
            raise WorkStop("Input identity changed during staging")
    finally:
        os.close(fd)
    now = int(time.time())
    grant_id = uuid.uuid4().hex
    with db(root) as conn:
        _schema(conn)
        _schema_tools(conn)
        _bindings_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        plan = conn.execute(
            "SELECT project,state FROM supervisor_plans WHERE id=?", (plan_id,)
        ).fetchone()
        step = conn.execute(
            "SELECT plan,prompt,state,run_id FROM supervisor_steps WHERE id=?", (step_id,)
        ).fetchone()
        if (plan is None or plan["project"] != project_id or plan["state"] != "draft"
                or step is None or step["plan"] != plan_id or step["state"] != "pending"
                or step["run_id"] is not None or step["prompt"] != expected_prompt(file_name)):
            raise WorkStop("Exact draft-plan step and approved-file prompt required")
        archived = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='project_archives'"
        ).fetchone()
        if archived and conn.execute(
            "SELECT 1 FROM project_archives WHERE project=?", (project_id,)
        ).fetchone():
            raise WorkStop("Archived Work project cannot stage a tool grant")
        if conn.execute("SELECT 1 FROM scorpio9c_step_bindings WHERE step=?", (step_id,)).fetchone():
            raise WorkStop("This step already has a staged grant")
        if conn.execute("SELECT count(*) FROM scorpio9c_step_bindings").fetchone()[0] >= MAX_STAGED:
            raise WorkStop("Staged grant inventory limit reached")
        conn.execute(
            "INSERT INTO scorpio9c_grants VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,0,?)",
            (grant_id, os.getuid(), project_id, plan_id, TOOL_ID, str(folder),
             file_name, info.st_dev, info.st_ino, info.st_size, sha, now + minutes * 60, now),
        )
        conn.execute("INSERT INTO scorpio9c_step_bindings VALUES (?,?,?,?,?)",
                     (step_id, grant_id, project_id, plan_id, now))
        conn.execute("INSERT INTO scorpio9c_events(grant_id,kind,at) VALUES (?,?,?)",
                     (grant_id, "staged.owner_terminal.draft_step", now))
    return {"grant_id": grant_id, "step_id": step_id, "plan": plan_id,
            "project": project_id, "tool": TOOL_ID, "file": file_name,
            "expires": now + minutes * 60, "worker_execution": "disabled"}


def _status(row: sqlite3.Row | None) -> str:
    if row is None:
        return "unbound"
    if row["revoked"]:
        return "revoked"
    if row["used"]:
        return "consumed"
    if row["expires"] <= int(time.time()):
        return "expired"
    if row["plan_state"] == "draft":
        return "awaiting_plan_approval"
    if row["plan_state"] in ("paused", "attention", "complete"):
        return "inactive_plan"
    if row["plan_state"] not in ("ready", "running"):
        return "denied"
    return "eligible_for_future_worker_only"


def bindings(root: Path, *, project_id: str | None = None) -> dict:
    """Owner terminal inspection of step->grant references; no raw paths/digests."""
    if project_id is not None:
        _id(project_id)
    with closing(_readonly_db(root)) as conn:
        if not _table(conn, "scorpio9c_step_bindings"):
            return {"bindings": [], "truncated": False, "worker_execution": "disabled"}
        sql = (
            "SELECT b.step,b.grant_id,b.project,b.plan,b.created,"
            "g.file_name,g.expires,g.revoked,g.used,p.state AS plan_state "
            "FROM scorpio9c_step_bindings b "
            "JOIN scorpio9c_grants g ON g.id=b.grant_id "
            "JOIN supervisor_plans p ON p.id=b.plan WHERE g.owner_uid=?"
        )
        params: list[str | int] = [os.getuid()]
        if project_id is not None:
            sql += " AND b.project=?"
            params.append(project_id)
        rows = conn.execute(sql + " ORDER BY b.created DESC,b.step DESC LIMIT 101", params).fetchall()
        return {"bindings": [{"step": x["step"], "grant_id": x["grant_id"],
                              "project": x["project"], "plan": x["plan"],
                              "file": x["file_name"], "expires": x["expires"],
                              "status": _status(x)} for x in rows[:100]],
                "truncated": len(rows) > 100, "worker_execution": "disabled"}


def check_queued_step(root: Path, run_id: str) -> dict:
    """Pure policy preview for an actual queued Work run; NEVER consumes a grant.

    The worker does not invoke this yet. A future executor MUST revalidate all
    identities/approval and consume the grant atomically before launching Bwrap.
    """
    _id(run_id)
    with closing(_readonly_db(root)) as conn:
        if not _table(conn, "scorpio9c_step_bindings"):
            raise WorkStop("No staged step bindings are recorded")
        row = conn.execute(
            "SELECT r.id,r.project AS run_project,r.state AS run_state,r.mode,r.prompt AS run_prompt,"
            "s.id AS step,s.prompt AS step_prompt,s.state AS step_state,"
            "p.id AS plan,p.project AS plan_project,p.state AS plan_state,"
            "g.id AS grant_id,g.owner_uid,g.project AS grant_project,g.plan AS grant_plan,"
            "g.tool,g.file_name,g.expires,g.revoked,g.used "
            "FROM runs r JOIN supervisor_steps s ON s.run_id=r.id "
            "JOIN supervisor_plans p ON p.id=s.plan "
            "JOIN scorpio9c_step_bindings b ON b.step=s.id "
            "JOIN scorpio9c_grants g ON g.id=b.grant_id WHERE r.id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise WorkStop("No owner-staged grant is bound to this queued run")
        if (row["run_project"] != row["plan_project"]
                or row["grant_project"] != row["run_project"]
                or row["grant_plan"] != row["plan"]
                or row["owner_uid"] != os.getuid()
                or row["tool"] != TOOL_ID
                or row["run_state"] != "queued" or row["mode"] != "pending"
                or row["step_state"] != "queued" or row["plan_state"] != "running"
                or row["step_prompt"] != expected_prompt(row["file_name"])
                or row["run_prompt"] != row["step_prompt"]
                or row["revoked"] or row["used"] or row["expires"] <= int(time.time())):
            raise WorkStop("Queued Work run fails exact staged-step grant policy")
        archived = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='project_archives'"
        ).fetchone()
        if archived and conn.execute(
            "SELECT 1 FROM project_archives WHERE project=?", (row["run_project"],)
        ).fetchone():
            raise WorkStop("Archived project has no tool privileges")
        return {"run": run_id, "step": row["step"], "grant": row["grant_id"],
                "tool": TOOL_ID, "metadata_precheck": "passed", "input_integrity": "not_verified",
                "worker_execution": "disabled"}
