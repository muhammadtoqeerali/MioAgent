"""Hard-delete or archive Work projects with private SQLite and attachment checks.

Work project data is distinct from legacy artifact Project Mode. Shared Studio
uploads are retained until no other Work project references them.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from collections.abc import Callable
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException

from mio.studio_files import StudioError
from mio.work_core import RUNTIME, WorkStop, _id, db
from mio.work_engineering import delete_artifact


def _table(conn) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS project_archives ("
                 "project TEXT PRIMARY KEY REFERENCES projects(id), archived_at INTEGER NOT NULL)")


def listed_projects(root: Path, *, archived: bool = False) -> list[dict]:
    with db(root) as conn:
        _table(conn)
        condition = "EXISTS" if archived else "NOT EXISTS"
        rows = conn.execute(
            f"SELECT p.* FROM projects p WHERE {condition} ("
            "SELECT 1 FROM project_archives a WHERE a.project=p.id) "
            "ORDER BY p.created DESC, p.rowid DESC LIMIT 30"
        )
        return [dict(row) for row in rows]


def _exists(conn, project_id: str) -> None:
    if conn.execute("SELECT 1 FROM projects WHERE id=?", (_id(project_id),)).fetchone() is None:
        raise WorkStop("Project does not exist")


def is_archived(root: Path, project_id: str) -> bool:
    with db(root) as conn:
        _table(conn)
        _exists(conn, project_id)
        return bool(conn.execute("SELECT 1 FROM project_archives WHERE project=?", (project_id,)).fetchone())


def archive_project(root: Path, project_id: str, *, archive: bool) -> dict:
    with db(root) as conn:
        _table(conn)
        conn.execute("BEGIN IMMEDIATE")
        _exists(conn, project_id)
        if archive:
            active = conn.execute("SELECT 1 FROM runs WHERE project=? AND state IN ('queued','running') LIMIT 1",
                                  (project_id,)).fetchone()
            if active:
                raise WorkStop("Finish the active project task before archiving")
            conn.execute("INSERT OR IGNORE INTO project_archives(project,archived_at) VALUES (?,?)",
                         (project_id, int(time.time())))
        else:
            conn.execute("DELETE FROM project_archives WHERE project=?", (project_id,))
    return {"archived": archive}


def _upload_path(file_id: str) -> tuple[Path, Path]:
    _id(file_id)
    folder = RUNTIME / "studio" / "attachments"
    return folder / (file_id + ".bin"), folder / (file_id + ".json")


def _check_upload_integrity(file_id: str) -> None:
    """Validate upload bytes, without re-extracting an older/scanned PDF."""
    binary, metadata = _upload_path(file_id)
    for path in (binary, metadata):
        info = path.lstat()
        if (path.is_symlink() or not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
            raise WorkStop("Unsafe attachment cannot be deleted")
    if binary.stat().st_size > 8 * 1024 * 1024 or metadata.stat().st_size > 32_768:
        raise WorkStop("Unexpected stored attachment size")
    info = json.loads(metadata.read_text(encoding="utf-8"))
    raw = binary.read_bytes()
    if (info.get("id") != file_id or info.get("bytes") != len(raw)
            or info.get("sha256") != hashlib.sha256(raw).hexdigest()):
        raise WorkStop("Stored upload changed; refusing destructive deletion")


def delete_project(root: Path, project_id: str) -> dict:
    """Delete durable Work DB content and uniquely owned Studio uploads.

    Shared uploads stay referenced and are never destroyed. Fail before DB
    deletion if an orphan candidate cannot be integrity-verified.
    """
    orphan: list[str] = []
    shared = 0
    with db(root) as conn:
        _table(conn)
        conn.execute("BEGIN IMMEDIATE")
        _exists(conn, project_id)
        active = conn.execute("SELECT 1 FROM runs WHERE project=? AND state IN ('queued','running') LIMIT 1",
                              (project_id,)).fetchone()
        if active:
            raise WorkStop("Cannot delete project while a Work run is active")
        linked = [row[0] for row in conn.execute("SELECT id FROM assets WHERE project=?", (project_id,))]
        for file_id in linked:
            others = conn.execute("SELECT count(*) FROM assets WHERE id=? AND project<>?",
                                  (file_id, project_id)).fetchone()[0]
            if others:
                shared += 1
            else:
                # Stored bytes must be authentic; scanned PDFs need not be parsed.
                _check_upload_integrity(file_id)
                orphan.append(file_id)
        run_ids = [row[0] for row in conn.execute(
            "SELECT id FROM runs WHERE project=?", (project_id,))]
        conn.execute("DELETE FROM events WHERE run IN (SELECT id FROM runs WHERE project=?)", (project_id,))
        run_count = len(run_ids)
        conn.execute("DELETE FROM runs WHERE project=?", (project_id,))
        conn.execute("DELETE FROM assets WHERE project=?", (project_id,))
        conn.execute("DELETE FROM memories WHERE project=?", (project_id,))
        conn.execute("DELETE FROM project_archives WHERE project=?", (project_id,))
        conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
    # DB commit occurred. Report any cleanup failure rather than silently claim
    # that deleted files are gone. Cleanup is scoped to validated original IDs.
    deleted = 0
    undeleted: list[str] = []
    for file_id in orphan:
        bpath, jpath = _upload_path(file_id)
        try:
            for p in (bpath, jpath):
                if p.is_symlink() or not p.is_file() or p.stat().st_uid != os.getuid():
                    raise WorkStop("Linked file changed after validation")
                p.unlink()
            deleted += 1
        except (OSError, WorkStop):
            undeleted.append(file_id)
    incomplete_artifacts = []
    for run_id in run_ids:
        try:
            delete_artifact(root, run_id)
        except (OSError, WorkStop, ValueError):
            incomplete_artifacts.append(run_id)
    return {"deleted": True, "runs_deleted": run_count,
            "uploads_deleted": deleted, "shared_uploads_retained": shared,
            "uploads_cleanup_incomplete": undeleted,
            "artifacts_cleanup_incomplete": incomplete_artifacts}


def register_work_lifecycle(app: FastAPI, require_token: Callable, root: Path) -> None:
    auth = [Depends(require_token)]

    def respond(operation: Callable, project_id: str, **kwargs):
        try:
            return operation(root, project_id, **kwargs)
        except (WorkStop, StudioError, OSError, ValueError) as exc:
            raise HTTPException(409, detail=str(exc)[:200]) from exc

    @app.post("/api/work/projects/{project_id}/archive", dependencies=auth)
    def archive(project_id: str):
        return respond(archive_project, project_id, archive=True)

    @app.post("/api/work/projects/{project_id}/restore", dependencies=auth)
    def restore(project_id: str):
        return respond(archive_project, project_id, archive=False)

    @app.delete("/api/work/projects/{project_id}", dependencies=auth)
    def erase(project_id: str):
        return respond(delete_project, project_id)
