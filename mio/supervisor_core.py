"""SCORPIO9A: durable, owner-approved sequential supervisor using the existing Work DB.

Never execute host tools, read arbitrary paths, infer grants or auto-retry a failed run.
The existing independent Work worker owns all task execution. SQLite BEGIN IMMEDIATE
serializes approval and queue dispatch against ordinary Work run submission.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path

from mio.work_core import WorkStop, _id, db

MAX_STEPS = 6
MAX_PLANS = 100


def _schema(conn: sqlite3.Connection) -> None:
    # Project lifecycle deletion cascades to supervisor metadata. No foreign key
    # to runs: project deletion currently removes runs before project rows.
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS supervisor_plans (
            id TEXT PRIMARY KEY,
            project TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            goal TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('draft','ready','running','paused','complete','attention')),
            created INTEGER NOT NULL, updated INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS supervisor_steps (
            id TEXT PRIMARY KEY,
            plan TEXT NOT NULL REFERENCES supervisor_plans(id) ON DELETE CASCADE,
            position INTEGER NOT NULL, prompt TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('pending','queued','done','attention')),
            run_id TEXT UNIQUE,
            UNIQUE(plan,position)
        );
        CREATE TABLE IF NOT EXISTS supervisor_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan TEXT NOT NULL REFERENCES supervisor_plans(id) ON DELETE CASCADE,
            phase TEXT NOT NULL, detail TEXT NOT NULL, created INTEGER NOT NULL
        );
    """)


def _event(conn: sqlite3.Connection, plan: str, phase: str, detail: str) -> None:
    conn.execute("INSERT INTO supervisor_events(plan,phase,detail,created) VALUES (?,?,?,?)",
                 (plan, phase, detail[:200], int(time.time())))


def _plan(conn: sqlite3.Connection, plan_id: str) -> sqlite3.Row:
    record = conn.execute("SELECT * FROM supervisor_plans WHERE id=?", (_id(plan_id),)).fetchone()
    if record is None:
        raise WorkStop("Supervisor plan unavailable")
    return record


def create_plan(root: Path, project_id: str, goal: str, steps: list[str]) -> dict:
    """Owner submits a *draft*: no model inference or execution at this stage."""
    project_id = _id(project_id)
    if not isinstance(goal, str) or not 10 <= len(goal.strip()) <= 1800:
        raise WorkStop("Supervisor goal must contain 10–1800 characters")
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise WorkStop("Supervisor needs 1–6 owner-reviewed bounded steps")
    if any(not isinstance(s, str) or not 8 <= len(s.strip()) <= 2500 for s in steps):
        raise WorkStop("Every bounded step must contain 8–2500 characters")
    now = int(time.time())
    plan_id = uuid.uuid4().hex
    with db(root) as conn:
        _schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone() is None:
            raise WorkStop("Project not found in the existing private Work database")
        # A separately archived project must not admit a new supervisor plan.
        conn.execute("CREATE TABLE IF NOT EXISTS project_archives ("
                     "project TEXT PRIMARY KEY REFERENCES projects(id), archived_at INTEGER NOT NULL)")
        if conn.execute("SELECT 1 FROM project_archives WHERE project=?", (project_id,)).fetchone():
            raise WorkStop("Restore the archived project before planning")
        if conn.execute("SELECT count(*) FROM supervisor_plans").fetchone()[0] >= MAX_PLANS:
            raise WorkStop("Supervisor plan limit reached")
        conn.execute("INSERT INTO supervisor_plans VALUES (?,?,?,?,?,?)",
                     (plan_id, project_id, goal.strip(), "draft", now, now))
        for index, prompt in enumerate(steps):
            conn.execute("INSERT INTO supervisor_steps VALUES (?,?,?,?,?,?)",
                         (uuid.uuid4().hex, plan_id, index, prompt.strip(), "pending", None))
        _event(conn, plan_id, "draft", "Owner saved a reviewable bounded task plan")
    return read_plan(root, plan_id)


def read_plan(root: Path, plan_id: str) -> dict:
    with db(root) as conn:
        _schema(conn)
        row = _plan(conn, plan_id)
        steps = [dict(item) for item in conn.execute(
            "SELECT * FROM supervisor_steps WHERE plan=? ORDER BY position", (plan_id,))]
        events = [dict(item) for item in conn.execute(
            "SELECT phase,detail,created FROM supervisor_events WHERE plan=? ORDER BY id DESC LIMIT 100",
            (plan_id,))]
        return {**dict(row), "steps": steps, "events": events}


def list_plans(root: Path) -> dict:
    with db(root) as conn:
        _schema(conn)
        rows = conn.execute("SELECT id,project,goal,state,created,updated FROM supervisor_plans "
                            "ORDER BY created DESC,id DESC LIMIT 100")
        return {"plans": [dict(item) for item in rows]}


def approve_plan(root: Path, plan_id: str) -> dict:
    with db(root) as conn:
        _schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        plan = _plan(conn, plan_id)
        if plan["state"] not in ("draft", "paused"):
            raise WorkStop("Only draft or paused plans can be explicitly approved")
        conn.execute("CREATE TABLE IF NOT EXISTS project_archives ("
                     "project TEXT PRIMARY KEY REFERENCES projects(id), archived_at INTEGER NOT NULL)")
        if conn.execute("SELECT 1 FROM project_archives WHERE project=?", (plan["project"],)).fetchone():
            raise WorkStop("Archived projects cannot run supervisor plans")
        conflicting = conn.execute("SELECT id FROM supervisor_plans "
                                   "WHERE state IN ('ready','running') AND id<>? LIMIT 1", (plan_id,)).fetchone()
        if conflicting:
            raise WorkStop("Only one approved supervisor plan may run at a time")
        conn.execute("UPDATE supervisor_plans SET state='ready',updated=? WHERE id=?",
                     (int(time.time()), plan_id))
        _event(conn, plan_id, "approved", "Authenticated owner explicitly approved bounded steps")
    return read_plan(root, plan_id)


def pause_plan(root: Path, plan_id: str) -> dict:
    """Stops *future* automatic dispatch only; does not cancel an active Work run."""
    with db(root) as conn:
        _schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        plan = _plan(conn, plan_id)
        if plan["state"] not in ("ready", "running"):
            raise WorkStop("Only an approved active plan can be paused")
        conn.execute("UPDATE supervisor_plans SET state='paused',updated=? WHERE id=?",
                     (int(time.time()), plan_id))
        _event(conn, plan_id, "paused", "Owner paused future automatic step dispatch")
    return read_plan(root, plan_id)


def advance_supervisor(root: Path) -> str | None:
    """Single owner-locked Work worker calls this on every queue iteration.

    Returns the queued Work run id, or None. A prior step is marked complete
    only for actual Work state 'answered'. Failed/review/interrupted halt plan.
    """
    with db(root) as conn:
        _schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        plan = conn.execute("SELECT * FROM supervisor_plans "
                            "WHERE state IN ('ready','running') ORDER BY created,id LIMIT 1").fetchone()
        if plan is None:
            return None
        plan_id = plan["id"]
        step = conn.execute("SELECT * FROM supervisor_steps WHERE plan=? AND state!='done' "
                            "ORDER BY position LIMIT 1", (plan_id,)).fetchone()
        if step is None:
            conn.execute("UPDATE supervisor_plans SET state='complete',updated=? WHERE id=?",
                         (int(time.time()), plan_id))
            _event(conn, plan_id, "complete", "Every Work run returned answered")
            return None
        if step["run_id"]:
            run = conn.execute("SELECT state FROM runs WHERE id=?", (step["run_id"],)).fetchone()
            if run is None or run["state"] in ("failed", "interrupted", "needs_review"):
                conn.execute("UPDATE supervisor_steps SET state='attention' WHERE id=?", (step["id"],))
                conn.execute("UPDATE supervisor_plans SET state='attention',updated=? WHERE id=?",
                             (int(time.time()), plan_id))
                _event(conn, plan_id, "attention", "A Work run requires owner review; no auto-retry")
                return None
            if run["state"] in ("queued", "running"):
                return None
            if run["state"] != "answered":
                raise WorkStop("Unknown Work state; refusing automatic continuation")
            conn.execute("UPDATE supervisor_steps SET state='done' WHERE id=?", (step["id"],))
            _event(conn, plan_id, "step.answered", f"Step {step['position'] + 1} completed")
            step = conn.execute("SELECT * FROM supervisor_steps WHERE plan=? AND state='pending' "
                                "ORDER BY position LIMIT 1", (plan_id,)).fetchone()
            if step is None:
                conn.execute("UPDATE supervisor_plans SET state='complete',updated=? WHERE id=?",
                             (int(time.time()), plan_id))
                _event(conn, plan_id, "complete", "All approved steps returned answered")
                return None
        # A normal owner Work submission or another supervisor may already be queued.
        if conn.execute("SELECT 1 FROM runs WHERE state IN ('queued','running') LIMIT 1").fetchone():
            return None
        conn.execute("CREATE TABLE IF NOT EXISTS project_archives ("
                     "project TEXT PRIMARY KEY REFERENCES projects(id), archived_at INTEGER NOT NULL)")
        if conn.execute("SELECT 1 FROM project_archives WHERE project=?", (plan["project"],)).fetchone():
            conn.execute("UPDATE supervisor_plans SET state='attention',updated=? WHERE id=?",
                         (int(time.time()), plan_id))
            _event(conn, plan_id, "attention", "Project archived; no automated step dispatch")
            return None
        run_id = uuid.uuid4().hex
        now = int(time.time())
        conn.execute("INSERT INTO runs (id,project,prompt,state,mode,created,updated,sources) "
                     "VALUES (?,?,?,'queued','pending',?,?,'[]')",
                     (run_id, plan["project"], step["prompt"], now, now))
        conn.execute("INSERT INTO events(run,phase,detail,created) VALUES (?,?,?,?)",
                     (run_id, "queued", "Approved Scorpio supervisor bounded step", now))
        conn.execute("UPDATE supervisor_steps SET state='queued',run_id=? WHERE id=?",
                     (run_id, step["id"]))
        conn.execute("UPDATE supervisor_plans SET state='running',updated=? WHERE id=?", (now, plan_id))
        _event(conn, plan_id, "step.queued", f"Approved bounded step {step['position'] + 1} queued")
        return run_id
