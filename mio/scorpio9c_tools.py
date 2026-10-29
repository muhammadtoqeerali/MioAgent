"""SCORPIO9C1: local-only, single-use, plan-scoped, offline file digest tool.

This deliberately has no general tool execution, web interface, agent hook or shell.
Only an interactive owner terminal can issue or revoke grants. The worker remains
unchanged. Any host sandbox failure is a denial, never an unsandboxed fallback.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import time
import uuid
from pathlib import Path

from mio.supervisor_core import _schema
from mio.work_core import WorkStop, _id, db

TOOL_ID = "workspace.sha256.v1"
MAX_BYTES = 1024 * 1024
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z")
TOOLS = ({
    "id": TOOL_ID,
    "version": "1.0",
    "execution": "owner_console_only",
    "class": "read_only",
    "network": False,
    "sandbox": "bubblewrap_required",
    "external_skills": False,
    "automatic_approval": False,
    "max_input_bytes": MAX_BYTES,
    "timeout_seconds": 8,
    "description": "SHA-256 digest of one approved private input (no raw data output)",
},)


def registry() -> dict:
    return {"tools": list(TOOLS), "external_skills": "disabled", "worker_execution": "disabled"}


def _schema_tools(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS scorpio9c_grants (
          id TEXT PRIMARY KEY,
          owner_uid INTEGER NOT NULL,
          project TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          plan TEXT NOT NULL REFERENCES supervisor_plans(id) ON DELETE CASCADE,
          tool TEXT NOT NULL,
          resource_dir TEXT NOT NULL,
          file_name TEXT NOT NULL,
          device INTEGER NOT NULL,
          inode INTEGER NOT NULL,
          size INTEGER NOT NULL,
          expected_sha TEXT NOT NULL,
          expires INTEGER NOT NULL,
          used INTEGER NOT NULL DEFAULT 0,
          revoked INTEGER NOT NULL DEFAULT 0,
          created INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS scorpio9c_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          grant_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          at INTEGER NOT NULL
        );
    """)


def _record(conn: sqlite3.Connection, grant_id: str, kind: str) -> None:
    conn.execute("INSERT INTO scorpio9c_events(grant_id,kind,at) VALUES (?,?,?)",
                 (grant_id, kind, int(time.time())))


def _private_directory(folder: Path) -> None:
    info = folder.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077 or folder.resolve(strict=True) != folder):
        raise WorkStop("Tool input requires a private owner-owned real directory")


def input_directory(root: Path, project: str) -> Path:
    """Exactly one designated native Linux input directory per real Work project."""
    project = _id(project)
    work = Path(root)
    if not work.is_absolute() or work.is_symlink():
        raise WorkStop("Invalid Work root")
    runtime = work.parent
    base = runtime / "tool-inputs"
    target = base / project
    for folder in (runtime, base, target):
        _private_directory(folder)
    return target


def _open_input(root: Path, project: str, name: str) -> tuple[int, os.stat_result, Path]:
    if not isinstance(name, str) or not NAME.fullmatch(name) or name in (".", ".."):
        raise WorkStop("Invalid input filename")
    folder = input_directory(root, project)
    dirfd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dirfd)
        try:
            info = os.fstat(fd)
            directory_info = os.fstat(dirfd)
            current_info = folder.lstat()
            if ((directory_info.st_dev, directory_info.st_ino) !=
                    (current_info.st_dev, current_info.st_ino)):
                raise WorkStop("Input directory changed")
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_size > MAX_BYTES):
                raise WorkStop("Only small regular owner files are allowed")
            return fd, info, folder
        except BaseException:
            os.close(fd)
            raise
    finally:
        os.close(dirfd)


def _digest(fd: int) -> str:
    os.lseek(fd, 0, os.SEEK_SET)
    hasher = hashlib.sha256()
    total = 0
    while True:
        chunk = os.read(fd, 65536)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_BYTES:
            raise WorkStop("Input changed or exceeded size allowance")
        hasher.update(chunk)
    return hasher.hexdigest()


def _active(conn: sqlite3.Connection, project: str, plan: str) -> None:
    row = conn.execute("SELECT project,state FROM supervisor_plans WHERE id=?", (plan,)).fetchone()
    if row is None or row["project"] != project or row["state"] not in ("ready", "running"):
        raise WorkStop("A separately owner-approved active plan is required")
    archive = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                           "AND name='project_archives'").fetchone()
    if archive and conn.execute("SELECT 1 FROM project_archives WHERE project=?", (project,)).fetchone():
        raise WorkStop("Archived Work project cannot use tools")


def grant(root: Path, project: str, plan: str, name: str, *, minutes: int = 10) -> dict:
    """Public grant entrypoint: never call from a route, model or worker."""
    if not os.isatty(0):
        raise WorkStop("Grant creation requires an interactive owner terminal")
    return _create_grant(root, project, plan, name, minutes=minutes)


def _create_grant(root: Path, project: str, plan: str, name: str, *, minutes: int = 10) -> dict:
    """Internal deterministic implementation for isolated offline tests."""
    _id(project)
    _id(plan)
    if type(minutes) is not int or not 1 <= minutes <= 30:
        raise WorkStop("Grant expiry must be 1 to 30 minutes")
    fd, info, directory = _open_input(root, project, name)
    try:
        expected = _digest(fd)
        if os.fstat(fd).st_size != info.st_size:
            raise WorkStop("Input changed during review")
    finally:
        os.close(fd)
    grant_id = uuid.uuid4().hex
    now = int(time.time())
    with db(root) as conn:
        _schema(conn)
        _schema_tools(conn)
        conn.execute("BEGIN IMMEDIATE")
        _active(conn, project, plan)
        if conn.execute("SELECT count(*) FROM scorpio9c_grants").fetchone()[0] >= 1000:
            raise WorkStop("Grant inventory limit reached")
        conn.execute("INSERT INTO scorpio9c_grants VALUES "
                     "(?,?,?,?,?,?,?,?,?,?,?,?,0,0,?)",
                     (grant_id, os.getuid(), project, plan, TOOL_ID, str(directory), name,
                      info.st_dev, info.st_ino, info.st_size, expected, now + minutes * 60, now))
        _record(conn, grant_id, "issued.local_console")
    return {"id": grant_id, "tool": TOOL_ID, "file": name,
            "project": project, "plan": plan, "expires": now + minutes * 60}


def revoke(root: Path, grant_id: str) -> None:
    if not os.isatty(0):
        raise WorkStop("Revocation requires an interactive owner terminal")
    with db(root) as conn:
        _schema_tools(conn)
        conn.execute("BEGIN IMMEDIATE")
        changed = conn.execute("UPDATE scorpio9c_grants SET revoked=1 "
                               "WHERE id=? AND owner_uid=?", (_id(grant_id), os.getuid()))
        if changed.rowcount != 1:
            raise WorkStop("Owner grant unavailable")
        _record(conn, grant_id, "revoked.local_console")


def _sandbox_digest(fd: int) -> str:
    executable = shutil.which("bwrap")
    if not executable or not Path("/usr/bin/sha256sum").is_file():
        raise WorkStop("Bubblewrap or system sha256sum unavailable; execution denied")
    command = [
        # Legacy bwrap has no --clearenv. subprocess.run(env=...) scrubs the host environment.
        executable, "--die-with-parent", "--unshare-all", "--new-session",
        "--setenv", "PATH", "/usr/bin:/bin",
        "--ro-bind", "/usr", "/usr",
        "--ro-bind-try", "/lib", "/lib",
        "--ro-bind-try", "/lib64", "/lib64",
        "--ro-bind-try", "/bin", "/bin",
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
        "--ro-bind-data", str(fd), "/tmp/input", "--",
        "/usr/bin/sha256sum", "/tmp/input",
    ]
    os.lseek(fd, 0, os.SEEK_SET)
    try:
        outcome = subprocess.run(command, pass_fds=(fd,), cwd="/", env={"PATH": "/usr/bin:/bin"},
                                 capture_output=True, timeout=8, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorkStop("Required isolated execution failed; grant consumed") from exc
    if outcome.returncode or len(outcome.stdout) > 128:
        raise WorkStop("Required isolated execution rejected; grant consumed")
    try:
        digest, path = outcome.stdout.decode("ascii", "strict").strip().split(maxsplit=1)
    except (UnicodeDecodeError, ValueError) as exc:
        raise WorkStop("Invalid sandbox output") from exc
    if len(digest) != 64 or not re.fullmatch(r"[0-9a-f]{64}", digest) or path != "/tmp/input":
        raise WorkStop("Invalid isolated digest response")
    return digest


def inspect(root: Path, grant_id: str, name: str) -> dict:
    """Consumes an exact grant before starting the Bwrap child (never retries)."""
    _id(grant_id)
    fd = None
    try:
        with db(root) as conn:
            _schema(conn)
            _schema_tools(conn)
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM scorpio9c_grants WHERE id=?", (grant_id,)).fetchone()
            if (row is None or row["owner_uid"] != os.getuid() or row["used"]
                    or row["revoked"] or row["expires"] <= int(time.time())):
                raise WorkStop("Grant missing, expired, revoked or already consumed")
            if row["tool"] != TOOL_ID or row["file_name"] != name:
                raise WorkStop("Operation or resource not authorized")
            _active(conn, row["project"], row["plan"])
            fd, info, folder = _open_input(root, row["project"], name)
            if (str(folder) != row["resource_dir"] or (info.st_dev, info.st_ino, info.st_size) !=
                    (row["device"], row["inode"], row["size"])):
                raise WorkStop("Scoped input identity changed")
            before = _digest(fd)
            if before != row["expected_sha"] or os.fstat(fd).st_size != row["size"]:
                raise WorkStop("Scoped input content changed")
            changed = conn.execute("UPDATE scorpio9c_grants SET used=1 WHERE id=? AND used=0",
                                   (grant_id,))
            if changed.rowcount != 1:
                raise WorkStop("Grant already consumed")
            _record(conn, grant_id, "consumed.before_sandbox")
        result = _sandbox_digest(fd)
        if result != before or _digest(fd) != before:
            raise WorkStop("Isolated result or original input changed")
        with db(root) as conn:
            _schema_tools(conn)
            _record(conn, grant_id, "sandbox.sha256.success")
        return {"grant_id": grant_id, "tool": TOOL_ID, "sha256": result}
    finally:
        if fd is not None:
            os.close(fd)
