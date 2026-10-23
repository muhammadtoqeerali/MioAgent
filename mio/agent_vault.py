"""MioAgent project-contained owner-private vault and verified runtime checkpoints.

No writes to legacy runtime: only online SQLite backups and verified copies. No
configuration outside the checked-out MioAgent repository is created or changed.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import time
import uuid
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
VAULT = PROJECT / ".mioagent-private"
RUNTIME = Path(f"/var/tmp/mioagent-native-{os.getuid()}")
LAYOUT = (
    "data/chat", "data/work", "studio/omni-images", "studio/attachments",
    "studio/jobs", "projects", "workspaces", "artifacts", "agents/grants",
    "agents/audit", "agents/workspaces", "backups", "state",
)
PNG = b"\x89PNG\r\n\x1a\n"
MAX_SINGLE_FILE = 8 * 1024 * 1024 * 1024  # fail closed on unexpected huge files
MIN_FREE_AFTER = 2 * 1024 * 1024 * 1024


class VaultError(RuntimeError):
    """Unsafe input, filesystem, or snapshot state; do not continue."""


PORTABLE_TYPES = frozenset({"fuseblk", "ntfs3", "ntfs", "ntfs-3g", "fuse.ntfs-3g"})


def filesystem_type(path: Path = PROJECT) -> str:
    """Inspect only the existing filesystem mount; never run a mount operation."""
    try:
        result = subprocess.run(["findmnt", "-n", "-o", "FSTYPE", "-T", str(path)],
                                check=True, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise VaultError("Cannot verify MioAgent storage filesystem") from exc
    return result.stdout.strip().lower()


def compatibility_storage(path: Path) -> bool:
    """Allow mode-emulated files only within the provisional project checkpoint.

    Never use this exception for /var/tmp live data, for arbitrary host paths,
    or as authority to grant tools or activate a live database.
    """
    if VAULT != PROJECT / ".mioagent-private":
        return False  # isolated test fixture and alternate paths remain strict
    if path != VAULT and VAULT not in path.parents:
        return False
    return (project_boundary() == "root-owned-world-writable-compatibility"
            and filesystem_type() in PORTABLE_TYPES)


def project_storage_status() -> dict:
    """Honest description of the current mount; does not assert confidentiality."""
    return {"filesystem": filesystem_type(), "boundary": project_boundary(),
            "native_private_mode": not compatibility_storage(VAULT),
            "live_cutover_supported": project_boundary() == "owner-controlled"
                                       and filesystem_type() not in PORTABLE_TYPES}


def _directory(path: Path, *, private: bool = True) -> None:
    if path.is_symlink() or not path.is_dir():
        raise VaultError("Invalid directory or symlink: " + path.name)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise VaultError("Invalid directory type: " + path.name)
    if compatibility_storage(path):
        # NTFS/FUSE mounts can report synthesized root UID / 0777 regardless of
        # mkdir(mode=0700). This is a copy-only, non-authoritative checkpoint.
        if info.st_uid not in (0, os.getuid()):
            raise VaultError("Unexpected portable checkpoint directory owner")
        return
    if info.st_uid != os.getuid():
        raise VaultError("Directory not owned by current user: " + path.name)
    if stat.S_IMODE(info.st_mode) & (0o077 if private else 0o022):
        raise VaultError("Directory permissions too broad: " + path.name)


def _file(path: Path, *, private: bool = True, max_bytes: int = MAX_SINGLE_FILE) -> os.stat_result:
    if path.is_symlink():
        raise VaultError("File symlink refused")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise VaultError("Unsafe file kind")
    if compatibility_storage(path):
        if info.st_uid not in (0, os.getuid()):
            raise VaultError("Unexpected portable checkpoint file owner")
    else:
        if info.st_uid != os.getuid():
            raise VaultError("Unsafe file owner")
        if private and stat.S_IMODE(info.st_mode) & 0o077:
            raise VaultError("Private file permissions too broad")
    if info.st_size > max_bytes:
        raise VaultError("File size exceeds snapshot bound")
    return info


def project_boundary_policy(info: os.stat_result, uid: int) -> str:
    """Distinguish owner-controlled checkout from an explicitly recognized root 0777 mount.

    Root-owned 0777 remains vulnerable to peer-account renaming/replacement;
    this limited compatibility mode is allowed for additive checkpoints only.
    """
    if not stat.S_ISDIR(info.st_mode):
        raise VaultError("Project checkout is not a directory")
    mode = stat.S_IMODE(info.st_mode)
    if info.st_uid == uid and not mode & 0o022:
        return "owner-controlled"
    if info.st_uid == 0 and uid != 0 and mode == 0o777:
        return "root-owned-world-writable-compatibility"
    raise VaultError("Project checkout ownership/mode not an approved layout")


def project_boundary() -> str:
    if (PROJECT.as_posix() != "/mnt/hdd16T/ToqeerHomeBackup/toqeer/MioAgent"
            or PROJECT.is_symlink() or not PROJECT.is_dir()
            or PROJECT.resolve() != PROJECT):
        raise VaultError("Unexpected or linked MioAgent checkout")
    return project_boundary_policy(PROJECT.lstat(), os.getuid())


def prepare() -> Path:
    """Create checkpoint folders inside MioAgent; do not claim NTFS Unix privacy."""
    project_boundary()
    if VAULT.exists() or VAULT.is_symlink():
        _directory(VAULT)
    else:
        VAULT.mkdir(mode=0o700)
        _directory(VAULT)
    for relative in LAYOUT:
        current = VAULT
        for part in Path(relative).parts:
            current = current / part
            if current.exists() or current.is_symlink():
                _directory(current)
            else:
                current.mkdir(mode=0o700)
                _directory(current)
    return VAULT


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _write_new(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _copy_verified(src: Path, dst: Path, *, png: bool = False) -> dict:
    original = _file(src)
    if dst.exists() or dst.is_symlink():
        raise VaultError("Snapshot destination unexpectedly exists")
    if shutil.disk_usage(dst.parent).free < original.st_size + MIN_FREE_AFTER:
        raise VaultError("Not enough free disk space to preserve reserve")
    src_digest = _digest(src)
    fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as target, src.open("rb") as source:
            shutil.copyfileobj(source, target, length=1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
        new = _file(dst)
        if new.st_size != original.st_size or _digest(dst) != src_digest:
            raise VaultError("Copied file integrity mismatch")
        if png:
            with dst.open("rb") as image:
                valid_png = image.read(8) == PNG
            if new.st_size <= 8 or not valid_png:
                raise VaultError("Private PNG signature invalid")
        if _file(src).st_size != original.st_size or _digest(src) != src_digest:
            raise VaultError("Source changed while copying")
    except BaseException:
        dst.unlink(missing_ok=True)
        raise
    return {"bytes": original.st_size, "sha256": src_digest}


def _sqlite_backup(src: Path, dst: Path) -> dict:
    _file(src)  # Owner-only private source; never open an arbitrary host SQLite path.
    if dst.exists() or dst.is_symlink():
        raise VaultError("Database checkpoint already exists")
    # SQLite backup API includes committed WAL state; never simply copy a live DB.
    source = sqlite3.connect(f"{src.as_uri()}?mode=ro", uri=True, timeout=10)
    _write_new(dst, b"")  # Private inode exists before SQLite writes begin.
    target = sqlite3.connect(str(dst), timeout=10)
    try:
        source.backup(target, pages=128, sleep=0.1)
        target.commit()
        check = target.execute("PRAGMA quick_check").fetchone()[0]
        if check != "ok":
            raise VaultError("SQLite checkpoint integrity failed")
    finally:
        target.close()
        source.close()
    if not compatibility_storage(dst):
        os.chmod(dst, 0o600)
    _file(dst)
    return {"bytes": dst.stat().st_size, "sha256": _digest(dst), "sqlite_quick_check": "ok"}


def _scan_tree(base: Path):
    """Never follow a symlink; use only managed runtime child trees."""
    _directory(base)
    for root, dirs, files in os.walk(base, topdown=True, followlinks=False):
        parent = Path(root)
        _directory(parent)
        for name in sorted(dirs):
            _directory(parent / name)
        for name in sorted(files):
            path = parent / name
            _file(path)
            yield path, path.relative_to(base)


def checkpoint(*, copy_live_images: bool = True) -> dict:
    """Create additive, checksum-verified project-local backup and image seed.

    Caller must verify idle API/Work/Comfy queues, and then keep writers idle
    during the snapshot. Existing files are never replaced or removed.
    """
    prepare()
    _directory(RUNTIME)
    for root_name in ("data", "work", "studio"):
        _directory(RUNTIME / root_name)
    if (RUNTIME / "projects").exists():
        _directory(RUNTIME / "projects")
    backup_root = VAULT / "backups"
    label = time.strftime("checkpoint-%Y%m%dT%H%M%SZ-", time.gmtime()) + uuid.uuid4().hex[:12]
    stage = backup_root / (".pending-" + label)
    stage.mkdir(mode=0o700)
    catalog = {}
    count = 0
    try:
        for group in ("data", "work", "studio", "projects"):
            original = RUNTIME / group
            if not original.exists():
                continue
            _directory(original)
            for file, relative in _scan_tree(original):
                # SQLite main DBs get online backups instead; -wal/-shm and locks are volatile.
                if file.name.endswith(("-wal", "-shm", ".lock")) or file.name in ("work-worker.lock",):
                    continue
                target = stage / group / relative
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                for part in [target.parent, *target.parent.parents]:
                    if part == stage.parent:
                        break
                    if stage == part or stage in part.parents:
                        _directory(part)
                if (group, relative.as_posix()) in (("data", "mioagent.db"), ("work", "work.db")):
                    catalog[f"{group}/{relative.as_posix()}"] = _sqlite_backup(file, target)
                else:
                    catalog[f"{group}/{relative.as_posix()}"] = _copy_verified(file, target, png=file.suffix.lower() == ".png")
                count += 1
                if count > 100_000:
                    raise VaultError("Too many files in runtime snapshot")
        # Preserve private runtime settings and credentials inside this project-only archive.
        # A world-writable project parent permits same-directory renaming by peer
        # users. Do not put live credentials into this provisional checkpoint.
        settings = (("api-token", "model.env", "project-mode-enabled", "sandbox-verify-enabled")
                    if project_boundary() == "owner-controlled" else ())
        for filename in settings:
            source = RUNTIME / filename
            if source.exists() or source.is_symlink():
                target = stage / "state" / filename
                target.parent.mkdir(mode=0o700, exist_ok=True)
                catalog["state/" + filename] = _copy_verified(source, target)
                count += 1
        # Don't activate image-path switch before every existing image has a verified copy.
        images = RUNTIME / "studio" / "omni-images"
        if copy_live_images and images.is_dir():
            _directory(images)
            for file, _relative in _scan_tree(images):
                if file.suffix != ".png":
                    raise VaultError("Unexpected file in live image directory")
                new = VAULT / "studio" / "omni-images" / file.name
                if new.is_file() and not new.is_symlink():
                    _file(new)
                    if _digest(new) != _digest(file):
                        raise VaultError("Existing destination image differs from live image")
                elif new.exists() or new.is_symlink():
                    raise VaultError("Unsafe destination image exists")
                else:
                    _copy_verified(file, new, png=True)
        manifest = {"format": 1, "created_utc": label, "files": catalog,
                    "source": "existing managed native runtime; preserved in place",
                    "storage_status": project_storage_status(),
                    "private_file_access_enforced": not compatibility_storage(VAULT),
                    "active_db_cutover": False}
        _write_new(stage / "manifest.json", json.dumps(manifest, sort_keys=True, indent=2).encode())
        complete = backup_root / label
        stage.rename(complete)
        return {"checkpoint": str(complete), "files": count, "image_store": str(VAULT / "studio/omni-images"),
                "databases_moved": False, "source_preserved": True}
    except Exception as exc:
        # Retain the partial stage for recovery; never delete any earlier files.
        raise VaultError("Checkpoint incomplete; partial stage preserved") from exc


def validate_live_image_store() -> Path:
    """Called by active API after a separately approved deployment."""
    if (project_boundary() != "owner-controlled"
            or filesystem_type() in PORTABLE_TYPES):
        raise VaultError("Live vault cutover blocked: parent or filesystem cannot provide private native storage")
    for relative in ("", "studio", "studio/omni-images"):
        _directory(VAULT / relative)
    return VAULT / "studio/omni-images"
