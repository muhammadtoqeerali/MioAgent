"""Private, persistent project sessions and tool-action audit trail.

The owner explicitly creates projects and memories. Model output cannot grant tools,
select arbitrary host paths or silently publish changes. SQLite is on native Linux.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import stat
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from mio.studio_files import StudioError, private_root, read_attachment

RUNTIME = Path(f"/var/tmp/mioagent-native-{os.getuid()}")
ID = re.compile(r"[0-9a-f]{32}\Z")
MAX_EVENTS = 200
MAX_PROJECTS = 30
MAX_MEMORIES = 40
MAX_ASSETS = 30
STATES = {"queued", "running", "answered", "needs_review", "failed", "interrupted"}
SKILLS = (
    {"id": "research", "title": "Evidence-based research", "tools": ["web.search", "model.research", "model.review"],
     "description": "Live public search snippets with cited sources and independent review"},
    {"id": "documents", "title": "Document analysis", "tools": ["file.read_attached", "model.writing", "model.review"],
     "description": "Inspect owner-uploaded files; no arbitrary workstation file access"},
    {"id": "conversation", "title": "General conversation", "tools": ["model.chat"],
     "description": "Use approved local models and optional project memories"},
)


class WorkStop(ValueError):
    """Owner action invalid, refused without accessing host resources."""


def _id(value: str) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise WorkStop("Invalid project or run identifier")
    return value


def _root(root: Path) -> Path:
    root = Path(root)
    if not root.is_absolute() or root.is_symlink():
        raise WorkStop("Private Work root must be an absolute non-symlink directory")
    try:
        parent = root.parent
        if not parent.exists() or parent.is_symlink():
            raise WorkStop("Private runtime parent is unavailable")
        parent_info = parent.lstat()
        if (parent_info.st_uid != os.getuid() or not stat.S_ISDIR(parent_info.st_mode)
                or stat.S_IMODE(parent_info.st_mode) & 0o077):
            raise WorkStop("Work store parent must be owner-private")
        return private_root(root)
    except StudioError as exc:
        raise WorkStop(str(exc)) from exc


@contextmanager
def db(root: Path):
    store = _root(root)
    path = store / "work.db"
    if path.is_symlink():
        raise WorkStop("Work database cannot be a symlink")
    connection = sqlite3.connect(str(path), timeout=8)
    try:
        path.chmod(0o600)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=8000")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, instructions TEXT NOT NULL,
                created INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY, project TEXT NOT NULL REFERENCES projects(id),
                content TEXT NOT NULL, created INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS assets (
                project TEXT NOT NULL REFERENCES projects(id),
                id TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
                PRIMARY KEY(project,id)
            );
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, project TEXT NOT NULL REFERENCES projects(id),
                prompt TEXT NOT NULL, state TEXT NOT NULL, mode TEXT NOT NULL,
                result TEXT, model TEXT, sources TEXT NOT NULL DEFAULT '[]',
                error TEXT, created INTEGER NOT NULL, updated INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run TEXT NOT NULL REFERENCES runs(id), phase TEXT NOT NULL,
                detail TEXT NOT NULL, created INTEGER NOT NULL
            );
        """)
        yield connection
        connection.commit()
    finally:
        connection.close()


def rowdict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def create_project(root: Path, title: str, instructions: str) -> dict:
    if not 3 <= len(title.strip()) <= 120 or len(instructions) > 6000:
        raise WorkStop("Project title or instructions exceed limits")
    project = {"id": uuid.uuid4().hex, "title": title.strip(),
               "instructions": instructions.strip(), "created": int(time.time())}
    with db(root) as conn:
        count = conn.execute("SELECT count(*) FROM projects").fetchone()[0]
        if count >= MAX_PROJECTS:
            raise WorkStop("Project limit reached")
        conn.execute("INSERT INTO projects VALUES (:id,:title,:instructions,:created)", project)
    return project


def projects(root: Path) -> list[dict]:
    with db(root) as conn:
        return [rowdict(x) for x in conn.execute("SELECT * FROM projects ORDER BY created DESC LIMIT 30")]


def project_info(root: Path, project_id: str) -> dict:
    with db(root) as conn:
        project = conn.execute("SELECT * FROM projects WHERE id=?", (_id(project_id),)).fetchone()
        if project is None:
            raise WorkStop("Project does not exist")
        return {**rowdict(project),
                "memories": [rowdict(x) for x in conn.execute(
                    "SELECT * FROM memories WHERE project=? ORDER BY created DESC LIMIT ?", (project_id, MAX_MEMORIES))],
                "assets": [rowdict(x) for x in conn.execute(
                    "SELECT * FROM assets WHERE project=? ORDER BY rowid DESC LIMIT ?", (project_id, MAX_ASSETS))],
                "runs": [rowdict(x) for x in conn.execute(
                    "SELECT id,prompt,state,mode,model,created,updated FROM runs WHERE project=? ORDER BY created DESC LIMIT 50", (project_id,))]}


def add_memory(root: Path, project_id: str, content: str) -> dict:
    if not isinstance(content, str) or not 3 <= len(content.strip()) <= 1500:
        raise WorkStop("Memory must be 3–1500 characters")
    project_info(root, project_id)
    value = {"id": uuid.uuid4().hex, "project": project_id, "content": content.strip(),
             "created": int(time.time())}
    with db(root) as conn:
        count = conn.execute("SELECT count(*) FROM memories WHERE project=?", (project_id,)).fetchone()[0]
        if count >= MAX_MEMORIES:
            raise WorkStop("Memory limit reached")
        conn.execute("INSERT INTO memories VALUES (:id,:project,:content,:created)", value)
    return value


def remove_memory(root: Path, project_id: str, memory_id: str) -> None:
    with db(root) as conn:
        deleted = conn.execute("DELETE FROM memories WHERE id=? AND project=?",
                               (_id(memory_id), _id(project_id))).rowcount
        if deleted != 1:
            raise WorkStop("Memory not found in this project")


def link_file(root: Path, project_id: str, file_id: str) -> dict:
    project_info(root, project_id)
    meta, _raw = read_attachment(RUNTIME / "studio" / "attachments", _id(file_id))
    value = {"project": project_id, "id": file_id, "name": meta["name"], "kind": meta["kind"]}
    with db(root) as conn:
        count = conn.execute("SELECT count(*) FROM assets WHERE project=?", (project_id,)).fetchone()[0]
        if count >= MAX_ASSETS:
            raise WorkStop("Project attachment limit reached")
        try:
            conn.execute("INSERT INTO assets VALUES (:project,:id,:name,:kind)", value)
        except sqlite3.IntegrityError as exc:
            raise WorkStop("File already linked to project") from exc
    return value


def create_run(root: Path, project_id: str, prompt: str, *, engineering: bool = False,
               inspection_sources: list[str] | None = None) -> dict:
    if not isinstance(prompt, str) or not 4 <= len(prompt.strip()) <= 6000:
        raise WorkStop("Task instructions must be 4–6000 characters")
    if engineering and inspection_sources is not None:
        raise WorkStop("Engineering and inspection are different task types")
    if inspection_sources is not None:
        from mio.agentic_plan_v06b import AgenticPreviewDenied, plan
        try:
            selected = plan(prompt, inspection_sources).sources
        except AgenticPreviewDenied as exc:
            raise WorkStop("Invalid owner-selected source allowlist") from exc
        source_json = json.dumps(list(selected))
    else:
        source_json = "[]"
    project_info(root, project_id)
    now = int(time.time())
    value = {"id": uuid.uuid4().hex, "project": project_id, "prompt": prompt.strip(),
             "state": "queued", "mode": ("inspection_queued" if inspection_sources is not None
             else ("engineering_queued" if engineering else "pending")),
             "source_json": source_json,
             "created": now, "updated": now}
    with db(root) as conn:
        conn.execute("BEGIN IMMEDIATE")
        running = conn.execute("SELECT count(*) FROM runs WHERE state IN ('queued','running')").fetchone()[0]
        if running:
            raise WorkStop("One Work run at a time; wait for it to finish")
        conn.execute("INSERT INTO runs (id,project,prompt,state,mode,created,updated,sources) VALUES "
                     "(:id,:project,:prompt,:state,:mode,:created,:updated,:source_json)", value)
        conn.execute("INSERT INTO events(run,phase,detail,created) VALUES (?,?,?,?)",
                     (value["id"], "queued", "Owner submitted project task", now))
        if inspection_sources is not None:
            conn.execute("INSERT INTO events(run,phase,detail,created) VALUES (?,?,?,?)",
                         (value["id"], "inspection.approved",
                          "Authenticated owner approved bounded static source inspection", now))
    return value


def event(root: Path, run_id: str, phase: str, detail: str) -> None:
    if len(phase) > 50 or len(detail) > 500:
        raise WorkStop("Event exceeds audit limits")
    with db(root) as conn:
        count = conn.execute("SELECT count(*) FROM events WHERE run=?", (_id(run_id),)).fetchone()[0]
        if count >= MAX_EVENTS:
            raise WorkStop("Run event limit reached")
        conn.execute("INSERT INTO events(run,phase,detail,created) VALUES (?,?,?,?)",
                     (run_id, phase, detail, int(time.time())))


def update(root: Path, run_id: str, state: str, *, mode: str | None = None,
           result: str | None = None, model: str | None = None,
           sources: list[dict] | None = None, error: str | None = None) -> None:
    if state not in STATES:
        raise WorkStop("Invalid run state")
    with db(root) as conn:
        record = conn.execute("SELECT state FROM runs WHERE id=?", (_id(run_id),)).fetchone()
        if record is None or record["state"] not in ("queued", "running"):
            raise WorkStop("A terminal run cannot be silently overwritten")
        conn.execute("UPDATE runs SET state=?, mode=COALESCE(?,mode), result=?, model=?, "
                     "sources=?,error=?,updated=? WHERE id=?",
                     (state, mode, result[:100_000] if result else None, model,
                      json.dumps(sources or [])[:30_000], error[:1000] if error else None,
                      int(time.time()), run_id))


def run_info(root: Path, run_id: str) -> dict:
    with db(root) as conn:
        row = conn.execute("SELECT * FROM runs WHERE id=?", (_id(run_id),)).fetchone()
        if row is None:
            raise WorkStop("Run not found")
        value = rowdict(row)
        value["sources"] = json.loads(value["sources"])
        value["events"] = [rowdict(x) for x in conn.execute(
            "SELECT phase,detail,created FROM events WHERE run=? ORDER BY id LIMIT ?", (run_id, MAX_EVENTS))]
        return value


def interrupt_orphaned(root: Path) -> None:
    """On API startup, never claim incomplete work is successful after a restart."""
    with db(root) as conn:
        count = conn.execute("SELECT count(*) FROM runs WHERE state IN ('running','queued')").fetchone()[0]
        if count:
            conn.execute("UPDATE runs SET state='interrupted',error='API restarted; run must be retried as a new task',updated=? "
                         "WHERE state IN ('running','queued')", (int(time.time()),))
