"""Offline, integrity-checked, bounded snapshots of MioAgent state.

Never changes the active runtime. Excludes API credentials and model configuration.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import stat
import subprocess
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

ALLOWED_FILESYSTEMS = frozenset({"ext4", "xfs", "btrfs", "zfs", "f2fs"})
TEMPORARY_PATHS = (Path("/tmp"), Path("/var/tmp"), Path("/run"), Path("/dev/shm"))
MAX_FILES = 20000
MAX_SINGLE_FILE = 128 * 1024 * 1024
DEFAULT_MAX_MIB = 2048
SCHEMA = 1


class StorageError(RuntimeError):
    """Do not create or trust a snapshot if a security/integrity guard fails."""


def filesystem_type(path: Path) -> str:
    """Query the actual mount containing a path; fail if it cannot be verified."""
    result = subprocess.run(
        ["findmnt", "-n", "-o", "FSTYPE", "-T", str(path)],
        check=True, capture_output=True, text=True, timeout=8,
    )
    return result.stdout.strip()


def _no_symlink_components(path: Path) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise StorageError("An absolute, normalized directory path is required")
    for candidate in (path, *path.parents):
        if candidate.is_symlink():
            raise StorageError(f"Symlink component is not allowed: {candidate}")


def _private_directory(path: Path) -> Path:
    _no_symlink_components(path)
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise StorageError(f"Missing directory: {path}") from exc
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise StorageError(f"Directory must be owned by the current user: {path}")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise StorageError(f"Directory must be owner-only (0700): {path}")
    return path


def _native_location(path: Path) -> Path:
    _no_symlink_components(path)
    if any(path == base or base in path.parents for base in TEMPORARY_PATHS):
        raise StorageError("Temporary/run filesystems cannot hold durable backups")
    if filesystem_type(path) not in ALLOWED_FILESYSTEMS:
        raise StorageError("Backup directory must be on a native Linux filesystem")
    return path


def initialize_target(path: Path) -> Path:
    """Create exactly one private backup directory in an existing writable native parent."""
    _native_location(path.parent)
    if path.exists() or path.is_symlink():
        return _private_directory(_native_location(path))
    if not path.parent.is_dir():
        raise StorageError("Parent directory must already exist")
    try:
        path.mkdir(mode=0o700)
    except OSError as exc:
        raise StorageError(f"Cannot create private destination: {exc}") from exc
    return _private_directory(_native_location(path))


def validate_target(path: Path, source: Path | None = None) -> Path:
    path = _private_directory(_native_location(path))
    if source is not None and (path == source or source in path.parents or path in source.parents):
        raise StorageError("Source and backup location must not contain one another")
    return path


def validate_source(runtime: Path) -> tuple[Path, Path, Path]:
    root = _private_directory(runtime)
    if filesystem_type(root) not in ALLOWED_FILESYSTEMS:
        raise StorageError("Active runtime is not on a supported native filesystem")
    data = _private_directory(root / "data")
    projects = root / "projects"
    if projects.exists() or projects.is_symlink():
        _private_directory(projects)
    database = data / "mioagent.db"
    if not database.is_file() or database.is_symlink():
        raise StorageError("MioAgent SQLite database is missing or unsafe")
    info = database.stat()
    if info.st_uid != os.getuid() or not stat.S_ISREG(info.st_mode):
        raise StorageError("Unexpected database ownership or file type")
    # SQLite may be created with 0644 by a normal 0022 umask. Its parent
    # is verified owner-only (0700), so non-owner reads are unreachable.
    # Still forbid non-owner write bits; never chmod active DB implicitly.
    if stat.S_IMODE(info.st_mode) & 0o022:
        raise StorageError("SQLite database must not be writable by other users")
    return root, projects, database


def _iter_project_files(projects: Path):
    if not projects.exists():
        return
    count = 0
    for base, dirs, files in os.walk(projects, followlinks=False):
        base_path = Path(base)
        for dirname in dirs:
            child = base_path / dirname
            meta = child.lstat()
            if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != os.getuid():
                raise StorageError("Project tree contains an unsafe directory")
        for filename in files:
            child = base_path / filename
            info = child.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_nlink != 1):
                raise StorageError(f"Unsafe artifact file: {child}")
            if info.st_size > MAX_SINGLE_FILE:
                raise StorageError(f"Artifact exceeds single-file limit: {child}")
            count += 1
            if count > MAX_FILES:
                raise StorageError("Project file-count limit exceeded")
            yield child, info


def _hash(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            total += len(chunk)
    return digest.hexdigest(), total


def inventory(runtime: Path, max_bytes: int = DEFAULT_MAX_MIB * 1024 * 1024) -> dict:
    _, projects, database = validate_source(runtime)
    database_bytes = database.stat().st_size
    if database_bytes > max_bytes:
        raise StorageError("Database is larger than snapshot budget")
    total = database_bytes
    count = 0
    for _, info in _iter_project_files(projects):
        total += info.st_size
        count += 1
        if total > max_bytes:
            raise StorageError("Runtime data exceeds snapshot budget")
    return {"database_bytes": database_bytes, "project_files": count, "estimated_bytes": total,
            "limit_bytes": max_bytes, "source_fs": filesystem_type(runtime)}


def _copy_checked(src: Path, dst: Path, expected_size: int) -> dict:
    dst.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    digest = hashlib.sha256()
    copied = 0
    with src.open("rb") as source, dst.open("xb") as target:
        os.chmod(dst, 0o600)
        while block := source.read(1024 * 1024):
            copied += len(block)
            if copied > MAX_SINGLE_FILE or copied > expected_size:
                raise StorageError("Artifact changed or exceeded its budget during backup")
            target.write(block)
            digest.update(block)
        target.flush()
        os.fsync(target.fileno())
    if copied != expected_size or src.stat().st_size != expected_size:
        raise StorageError("Project artifact changed during backup")
    return {"size": copied, "sha256": digest.hexdigest()}


def _db_backup(db: Path, destination: Path) -> None:
    source = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=10)
    try:
        if source.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise StorageError("Source database integrity check failed")
        with sqlite3.connect(destination) as target:
            source.backup(target, pages=64, sleep=0.03)
            if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise StorageError("Backup database integrity check failed")
    finally:
        source.close()
    os.chmod(destination, 0o600)


def _safe_relative(value: str) -> Path:
    candidate = PurePosixPath(value)
    if (not value or candidate.is_absolute() or ".." in candidate.parts or "\\" in value
            or candidate.parts[0] not in {"data", "projects"}
            or len(candidate.parts) < 2):
        raise StorageError("Invalid manifest file path")
    return Path(*candidate.parts)


def _check_budget(max_mib: int) -> int:
    if not 1 <= max_mib <= 16384:
        raise StorageError("Backup budget must be 1 to 16384 MiB")
    return max_mib * 1024 * 1024


def create_snapshot(runtime: Path, destination: Path, *, max_mib: int = DEFAULT_MAX_MIB) -> Path:
    """Call only when the MioAgent API/dashboard have been stopped by the operator."""
    maximum = _check_budget(max_mib)
    root, projects, db = validate_source(runtime)
    dest = validate_target(destination, source=root)
    estimate = inventory(root, maximum)
    free = shutil.disk_usage(dest).free
    # Do not consume a nearly-full system volume for a snapshot.
    required = max(128 * 1024 * 1024, estimate["estimated_bytes"] * 2)
    if free < required:
        raise StorageError("Not enough free native filesystem space for a safe snapshot")
    name = "snapshot-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)
    stage = dest / (".partial-" + name)
    stage.mkdir(mode=0o700)
    finished = dest / name
    try:
        (stage / "data").mkdir(mode=0o700)
        _db_backup(db, stage / "data" / "mioagent.db")
        files = {}
        sha, size = _hash(stage / "data" / "mioagent.db")
        files["data/mioagent.db"] = {"sha256": sha, "size": size}
        for original, info in _iter_project_files(projects):
            relative = original.relative_to(root)
            logical = relative.as_posix()
            _safe_relative(logical)
            files[logical] = _copy_checked(original, stage / relative, info.st_size)
        manifest = {
            "schema": SCHEMA, "created_utc": datetime.now(UTC).isoformat(),
            "purpose": "offline_integrity_snapshot", "excludes_credentials": True,
            "files": dict(sorted(files.items())),
        }
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        os.chmod(stage / "manifest.json", 0o600)
        verify_snapshot(stage)
        os.rename(stage, finished)
        return finished
    except BaseException:
        shutil.rmtree(stage)
        raise


def verify_snapshot(snapshot: Path) -> dict:
    _private_directory(snapshot)
    manifest_path = snapshot / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise StorageError("Snapshot manifest missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("schema") != SCHEMA or manifest.get("excludes_credentials") is not True
            or not isinstance(manifest.get("files"), dict)
            or "data/mioagent.db" not in manifest["files"]):
        raise StorageError("Unsupported or invalid snapshot manifest")
    listed = set()
    total = 0
    for logical, item in manifest["files"].items():
        relative = _safe_relative(logical)
        path = snapshot / relative
        if path.is_symlink() or not path.is_file():
            raise StorageError(f"Snapshot file missing or unsafe: {logical}")
        if not isinstance(item, dict) or not isinstance(item.get("size"), int):
            raise StorageError("Invalid file metadata")
        actual, size = _hash(path)
        if item.get("sha256") != actual or item["size"] != size:
            raise StorageError(f"Snapshot checksum mismatch: {logical}")
        listed.add(logical)
        total += size
    for base, dirs, files in os.walk(snapshot, followlinks=False):
        for dirname in dirs:
            child = Path(base) / dirname
            if child.is_symlink():
                raise StorageError("Unsafe snapshot directory symlink")
        for filename in files:
            child = Path(base) / filename
            relative = child.relative_to(snapshot).as_posix()
            if relative not in listed and relative != "manifest.json":
                raise StorageError(f"Unexpected snapshot file: {relative}")
    with sqlite3.connect(f"file:{(snapshot / 'data' / 'mioagent.db').as_posix()}?mode=ro", uri=True) as db:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise StorageError("Snapshot SQLite integrity check failed")
    return {"verified_files": len(listed), "total_bytes": total, "integrity": "passed"}
