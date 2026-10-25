"""SCORPIO9C2: non-mutating, sanitized views of native tool grants and audit.

No token, input digest, raw file bytes or private paths leave this module.
All grants are still owner-console-only; these reads cannot approve actions.
"""
from __future__ import annotations

import os
import sqlite3
import stat
import time
from pathlib import Path
from urllib.parse import quote

from mio.scorpio9c_tools import registry
from mio.work_core import RUNTIME, WorkStop

MAX_PUBLIC_GRANTS = 100
MAX_PUBLIC_EVENTS = 100


def _private_dir(folder: Path) -> None:
    try:
        s = folder.lstat()
    except FileNotFoundError as exc:
        raise WorkStop("Owner-private Work database unavailable") from exc
    if (not stat.S_ISDIR(s.st_mode) or s.st_uid != os.getuid()
            or stat.S_IMODE(s.st_mode) & 0o077):
        raise WorkStop("Owner-private Work directory verification failed")


def _readonly_db(root: Path) -> sqlite3.Connection:
    """Open the existing Work SQLite without creating new files or schemas.

    WorkRoot and its immediate parent must be real, private, owner-owned dirs.
    The DB must be an owner-owned regular file and cannot be a symlink.
    SQLite mode=ro and PRAGMA query_only prohibit data writes in this connection.
    """
    root = Path(root)
    if not root.is_absolute() or root.is_symlink() or root.parent.is_symlink():
        raise WorkStop("Invalid Work storage location")
    _private_dir(root.parent)
    _private_dir(root)
    path = root / "work.db"
    try:
        s = path.lstat()
    except FileNotFoundError as exc:
        raise WorkStop("Existing Work database unavailable") from exc
    if (not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid()
            or stat.S_IMODE(s.st_mode) & 0o077):
        raise WorkStop("Unsafe Work database for grant inventory")
    uri = f"file:{quote(str(path), safe='/')}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=3)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        return conn
    except BaseException:
        conn.close()
        raise


def _table(conn: sqlite3.Connection, name: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def _state(row: sqlite3.Row, now: int, archived: set[str]) -> str:
    if row["revoked"]:
        return "revoked"
    if row["used"]:
        return "consumed"
    if row["expires"] <= now:
        return "expired"
    if row["project"] in archived or row["plan_state"] not in ("ready", "running"):
        return "inactive_plan"
    return "available_console_only"


def grant_inventory(root: Path = RUNTIME / "work") -> dict:
    """Bounded read-only inspection. Never issue or consume a grant."""
    conn = _readonly_db(root)
    try:
        if not _table(conn, "scorpio9c_grants"):
            return {"grants": [], "events": [], "count": 0, "truncated": False,
                    "can_grant_from_api": False, "worker_execution": "disabled"}
        archived: set[str] = set()
        if _table(conn, "project_archives"):
            archived = {r[0] for r in conn.execute("SELECT project FROM project_archives LIMIT 1000")}
        rows = conn.execute(
            "SELECT g.id,g.owner_uid,g.project,g.plan,g.tool,g.file_name,g.expires,"
            "g.used,g.revoked,g.created,p.state AS plan_state "
            "FROM scorpio9c_grants AS g LEFT JOIN supervisor_plans AS p ON p.id=g.plan "
            "WHERE g.owner_uid=? ORDER BY g.created DESC,g.id DESC LIMIT ?",
            (os.getuid(), MAX_PUBLIC_GRANTS + 1),
        ).fetchall()
        more = len(rows) > MAX_PUBLIC_GRANTS
        now = int(time.time())
        selected = []
        for row in rows[:MAX_PUBLIC_GRANTS]:
            selected.append({
                "id": row["id"], "project": row["project"], "plan": row["plan"],
                "tool": row["tool"], "file": row["file_name"],
                "state": _state(row, now, archived), "expires": row["expires"],
                "created": row["created"],
            })
        events: list[dict] = []
        if _table(conn, "scorpio9c_events"):
            ids = {row["id"] for row in selected}
            if ids:
                # Only selected owner's grant events. No dynamic SQL identifiers.
                records = conn.execute(
                    "SELECT e.grant_id,e.kind,e.at FROM scorpio9c_events AS e "
                    "INNER JOIN scorpio9c_grants AS g ON e.grant_id=g.id "
                    "WHERE g.owner_uid=? ORDER BY e.id DESC LIMIT ?",
                    (os.getuid(), MAX_PUBLIC_EVENTS),
                ).fetchall()
                events = [dict(r) for r in records if r["grant_id"] in ids]
        return {"grants": selected, "events": events, "count": len(selected),
                "truncated": more, "can_grant_from_api": False,
                "worker_execution": "disabled"}
    finally:
        conn.close()


def tool_catalog() -> dict:
    """Built-in, reviewed registry. External skills/API/MCP are not executable."""
    return {**registry(), "grants_api": "read_only", "grant_creation": "owner_console_only"}
