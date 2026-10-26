"""SCORPIO9C4: one exact, owner-staged supervisor tool through the Work worker.

Only the pre-existing sequential Work worker calls this from work_agent.execute().
No general shell, arbitrary path, network, model-mediated tool grant or HTTP write.
A staged grant is consumed atomically with marking its queued run running.
"""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

from mio.scorpio9c3_step_grants import _bindings_schema, expected_prompt
from mio.scorpio9c_tools import (
    TOOL_ID,
    _digest,
    _open_input,
    _sandbox_digest,
    _schema_tools,
)
from mio.supervisor_core import _schema
from mio.work_core import WorkStop, _id, db, event, run_info, update

TOOL_PREFIX = "Compute SHA-256 for owner-approved file: "


def _binding_exists(root: Path, run_id: str) -> bool:
    with db(root) as conn:
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='scorpio9c_step_bindings'"
        ).fetchone() is None:
            return False
        return conn.execute(
            "SELECT 1 FROM supervisor_steps s "
            "JOIN scorpio9c_step_bindings b ON b.step=s.id WHERE s.run_id=? LIMIT 1",
            (run_id,),
        ).fetchone() is not None


def _claim(root: Path, run_id: str) -> tuple[int, str, str]:
    """In one private SQLite transaction, validate exact scope and claim once.

    Input FD remains open, and is passed unchanged to the isolated child.
    Any exception closes the FD. No subprocess is started inside the lock.
    """
    fd = None
    try:
        with db(root) as conn:
            _schema(conn)
            _schema_tools(conn)
            _bindings_schema(conn)
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT r.project AS run_project,r.state AS run_state,"
                "r.mode AS run_mode,r.prompt AS run_prompt,"
                "s.id AS step,s.state AS step_state,s.prompt AS step_prompt,"
                "p.id AS plan,p.project AS plan_project,p.state AS plan_state,"
                "b.project AS bound_project,b.plan AS bound_plan,"
                "g.id AS grant,g.owner_uid,g.project AS grant_project,"
                "g.plan AS grant_plan,g.tool,g.resource_dir,g.file_name,"
                "g.device,g.inode,g.size,g.expected_sha,g.expires,g.revoked,g.used "
                "FROM runs r "
                "JOIN supervisor_steps s ON s.run_id=r.id "
                "JOIN supervisor_plans p ON p.id=s.plan "
                "JOIN scorpio9c_step_bindings b ON b.step=s.id "
                "JOIN scorpio9c_grants g ON g.id=b.grant_id "
                "WHERE r.id=?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise WorkStop("No staged grant for this exact queued supervisor step")
            name = row["file_name"]
            if (
                row["run_state"] != "queued"
                or row["run_mode"] != "pending"
                or row["step_state"] != "queued"
                or row["plan_state"] != "running"
                or row["run_project"] != row["plan_project"]
                or row["bound_project"] != row["run_project"]
                or row["bound_plan"] != row["plan"]
                or row["grant_project"] != row["run_project"]
                or row["grant_plan"] != row["plan"]
                or row["owner_uid"] != os.getuid()
                or row["tool"] != TOOL_ID
                or row["step_prompt"] != expected_prompt(name)
                or row["run_prompt"] != row["step_prompt"]
                or row["revoked"]
                or row["used"]
                or row["expires"] <= int(time.time())
            ):
                raise WorkStop("Run, plan, step, grant or expiry policy denied")
            archived = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='project_archives'"
            ).fetchone()
            if archived and conn.execute(
                "SELECT 1 FROM project_archives WHERE project=?",
                (row["run_project"],),
            ).fetchone():
                raise WorkStop("Archived project cannot execute a tool")
            fd, info, folder = _open_input(root, row["run_project"], name)
            if (
                str(folder) != row["resource_dir"]
                or (info.st_dev, info.st_ino, info.st_size)
                != (row["device"], row["inode"], row["size"])
            ):
                raise WorkStop("Scoped input identity mismatch")
            original = _digest(fd)
            if original != row["expected_sha"] or os.fstat(fd).st_size != row["size"]:
                raise WorkStop("Scoped input content changed")
            now = int(time.time())
            changed = conn.execute(
                "UPDATE scorpio9c_grants SET used=1 WHERE id=? AND used=0 AND revoked=0 "
                "AND expires>?",
                (row["grant"], now),
            )
            if changed.rowcount != 1:
                raise WorkStop("Scoped grant already consumed or expired")
            changed = conn.execute(
                "UPDATE runs SET state='running',mode='tool_sha256',updated=? "
                "WHERE id=? AND state='queued' AND mode='pending'",
                (now, run_id),
            )
            if changed.rowcount != 1:
                raise WorkStop("Queued run was not available for exact tool claim")
            conn.execute(
                "INSERT INTO scorpio9c_events(grant_id,kind,at) VALUES (?,?,?)",
                (row["grant"], "consumed.worker.step_bound", now),
            )
            conn.execute(
                "INSERT INTO events(run,phase,detail,created) VALUES (?,?,?,?)",
                (run_id, "tool.claimed", "Exact owner-staged SHA-256 grant consumed", now),
            )
        claimed = fd
        fd = None
        return claimed, original, row["grant"]
    finally:
        if fd is not None:
            os.close(fd)


def _finish(root: Path, run_id: str, grant_id: str, original: str, fd: int) -> dict:
    actual = _sandbox_digest(fd)
    if actual != original or _digest(fd) != original:
        raise WorkStop("Sandbox result or owner input changed")
    # A pause or revocation *after* an already-consumed operation cannot stop
    # the child, but prevents reporting success if owner review intervened.
    with db(root) as conn:
        conn.execute("BEGIN IMMEDIATE")
        state = conn.execute(
            "SELECT r.state,p.state AS plan_state,g.revoked "
            "FROM runs r JOIN supervisor_steps s ON s.run_id=r.id "
            "JOIN supervisor_plans p ON p.id=s.plan "
            "JOIN scorpio9c_step_bindings b ON b.step=s.id "
            "JOIN scorpio9c_grants g ON g.id=b.grant_id "
            "WHERE r.id=? AND g.id=?",
            (run_id, grant_id),
        ).fetchone()
        if (state is None or state["state"] != "running"
                or state["plan_state"] != "running" or state["revoked"]):
            raise WorkStop("Owner policy changed during isolated execution")
        now = int(time.time())
        changed = conn.execute(
            "UPDATE runs SET state='answered',mode='tool_sha256',result=?,"
            "sources='[]',error=NULL,updated=? WHERE id=? AND state='running'",
            (f"Verified offline SHA-256: {actual}", now, run_id),
        )
        if changed.rowcount != 1:
            raise WorkStop("Work run state changed during execution")
        conn.execute(
            "INSERT INTO events(run,phase,detail,created) VALUES (?,?,?,?)",
            (run_id, "tool.verified", "Bubblewrap offline digest verified against grant", now),
        )
        conn.execute(
            "INSERT INTO scorpio9c_events(grant_id,kind,at) VALUES (?,?,?)",
            (grant_id, "sandbox.sha256.worker.success", now),
        )
    return run_info(root, run_id)


def maybe_execute_scoped_tool(root: Path, run_id: str, record: dict) -> dict | None:
    """Return None for ordinary Work runs; intercept all digest-like/bound runs.

    Invalid/unbound digest instructions are never passed through to an LLM
    that might claim to have executed a tool. Every denial halts the plan.
    """
    _id(run_id)
    if not (record["prompt"].startswith(TOOL_PREFIX) or _binding_exists(root, run_id)):
        return None
    fd = None
    try:
        fd, original, grant_id = _claim(root, run_id)
        return _finish(root, run_id, grant_id, original, fd)
    except (WorkStop, OSError, sqlite3.DatabaseError, ValueError) as exc:
        # No untrusted path or raw exception value is written to Work evidence.
        current = run_info(root, run_id)
        if current["state"] in ("queued", "running"):
            event(root, run_id, "tool.denied", "Bounded tool refused: " + type(exc).__name__)
            update(root, run_id, "needs_review", mode="tool_denied",
                   error="Owner review required: scoped tool execution denied")
        return run_info(root, run_id)
    finally:
        if fd is not None:
            os.close(fd)
