"""Offline encrypted export of MioAgent SQLite and approved project artifacts.

Archives remain encrypted when crossing untrusted mounts or SSH relays. A verified
snapshot is NOT a full restored runtime (SQLite stores absolute workspace paths).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

from mio.durable_storage import (
    MAX_FILES,
    MAX_SINGLE_FILE,
    StorageError,
    _check_budget,
    _iter_project_files,
    _safe_relative,
    validate_source,
)

SCHEMA = 1
GPG_CIPHER = "AES256"


def _hash(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        while block := f.read(1024 * 1024):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def _assert_regular_owned_output(output: Path) -> None:
    if not output.is_absolute() or ".." in output.parts:
        raise StorageError("Export file path must be absolute and normalized")
    if output.suffix != ".gpg":
        raise StorageError("Encrypted output must end in .gpg")
    if output.exists() or output.is_symlink():
        raise StorageError("Refusing to overwrite an existing file or symlink")
    parent = output.parent
    if not parent.is_dir() or parent.is_symlink() or not os.access(parent, os.W_OK):
        raise StorageError("Output directory must exist and be writable")
    # Private plaintext export is forbidden; only GPG ciphertext may use NTFS.
    if output == parent:
        raise StorageError("Export path cannot be a directory")


def _gpg_process(
    args: list[str], passphrase: str, homedir: Path, output_handle=None,
) -> subprocess.Popen:
    if len(passphrase) < 16:
        raise StorageError("Choose a unique encryption passphrase of at least 16 characters")
    if not shutil.which("gpg"):
        raise StorageError("GPG executable not found")
    # GPG home must be private native Linux storage, not the NTFS user home.
    homedir.mkdir(mode=0o700)
    fd_r, fd_w = os.pipe()
    try:
        args = [
            "gpg", "--no-options", "--homedir", str(homedir), "--no-tty",
            "--batch", "--pinentry-mode", "loopback",
            "--passphrase-fd", str(fd_r), *args,
        ]
        process = subprocess.Popen(
            args, stdin=subprocess.PIPE if "--symmetric" in args else subprocess.DEVNULL,
            stdout=subprocess.PIPE if "--decrypt" in args else output_handle,
            stderr=subprocess.PIPE, pass_fds=(fd_r,),
        )
        os.close(fd_r)
        fd_r = -1
        with os.fdopen(fd_w, "wb") as secret:
            fd_w = -1
            secret.write(passphrase.encode("utf-8") + b"\n")
        return process
    finally:
        if fd_r >= 0:
            os.close(fd_r)
        if fd_w >= 0:
            os.close(fd_w)


def _copy_sqlite(source: Path, destination: Path) -> None:
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as src:
        if src.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise StorageError("Source database failed SQLite integrity check")
        with sqlite3.connect(destination) as target:
            src.backup(target, pages=64, sleep=0.03)
            if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise StorageError("Export database failed SQLite integrity check")
    destination.chmod(0o600)


def _tar_regular(tf: tarfile.TarFile, path: Path, logical: str, size: int) -> None:
    entry = tarfile.TarInfo(logical)
    entry.size = size
    entry.mode = 0o600
    entry.uid = entry.gid = 0
    entry.mtime = 0
    with path.open("rb") as handle:
        tf.addfile(entry, handle)
    if path.stat().st_size != size:
        raise StorageError(f"Artifact changed during export: {logical}")


def export_encrypted(runtime: Path, output: Path, passphrase: str, max_mib: int = 2048) -> dict:
    """Requires the managed API/dashboard to be stopped by caller."""
    root, projects, database = validate_source(runtime)
    maximum = _check_budget(max_mib)
    _assert_regular_owned_output(output)
    if output.is_relative_to(root):
        raise StorageError("Ciphertext output must be outside live runtime")
    with tempfile.TemporaryDirectory(prefix="mioagent-sqlite-export-", dir="/var/tmp") as tmp:
        backup_db = Path(tmp) / "mioagent.db"
        _copy_sqlite(database, backup_db)
        entries: list[tuple[Path, str, int]] = []
        for original, info in _iter_project_files(projects):
            name = original.relative_to(root).as_posix()
            _safe_relative(name)
            entries.append((original, name, info.st_size))
        if len(entries) > MAX_FILES:
            raise StorageError("Too many project files")
        entries.insert(0, (backup_db, "data/mioagent.db", backup_db.stat().st_size))
        if sum(size for _, _, size in entries) > maximum:
            raise StorageError("Export exceeds configured storage budget")
        manifest = {"schema": SCHEMA, "excludes_credentials": True, "files": {}}
        for path, name, size in entries:
            sha, actual_size = _hash(path)
            if actual_size != size or actual_size > MAX_SINGLE_FILE:
                raise StorageError("Source changed or file exceeds per-file budget")
            manifest["files"][name] = {"sha256": sha, "size": size}
        # Reserve output atomically; never reuse another user's or previous ciphertext.
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            with os.fdopen(descriptor, "wb") as ciphertext:
                process = _gpg_process([
                    "--symmetric", "--cipher-algo", GPG_CIPHER, "--s2k-digest", "SHA512",
                    "--output", "-",
                ], passphrase, Path(tmp) / "gnupg", ciphertext)
            try:
                assert process.stdin is not None
                with tarfile.open(fileobj=process.stdin, mode="w|gz") as archive:
                    for path, logical, size in entries:
                        _tar_regular(archive, path, logical, size)
                    payload = json.dumps(manifest, sort_keys=True).encode("utf-8")
                    record = tarfile.TarInfo("manifest.json")
                    record.size = len(payload)
                    record.mode = 0o600
                    record.uid = record.gid = 0
                    record.mtime = 0
                    archive.addfile(record, io.BytesIO(payload))
                # The TarFile context closes the tar stream but not the underlying pipe.
                process.stdin.close()
                diagnostics = process.stderr.read().decode("utf-8", errors="replace")
                status = process.wait(timeout=120)
                if status != 0:
                    raise StorageError(f"Encryption failed (gpg exit {status}): {diagnostics[:300]}")
            except BaseException:
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()
                process.kill() if process.poll() is None else None
                process.wait()
                raise
            if output.stat().st_size == 0:
                raise StorageError("Encrypted output is empty")
            digest, bytes_count = _hash(output)
            return {"encrypted_file": str(output), "sha256": digest, "encrypted_bytes": bytes_count,
                    "artifact_files": len(entries) - 1, "encrypted_transport": True}
        except BaseException:
            output.unlink(missing_ok=True)
            raise


def _safe_archive_file(member: tarfile.TarInfo) -> str:
    path = PurePosixPath(member.name)
    if (not member.isfile() or path.is_absolute() or ".." in path.parts
            or "\\" in member.name or member.name == "manifest.json" and member.size > 2_000_000):
        raise StorageError("Archive contains an unsafe entry")
    if member.name != "manifest.json":
        _safe_relative(member.name)
    if member.size > MAX_SINGLE_FILE or member.size < 0:
        raise StorageError("Archive contains an oversized entry")
    return member.name


def verify_encrypted(archive: Path, passphrase: str, max_mib: int = 2048) -> dict:
    """Streaming decrypt: no plaintext archive extracted to Windows or network drives."""
    maximum = _check_budget(max_mib)
    if not archive.is_file() or archive.is_symlink():
        raise StorageError("Encrypted archive must be a regular non-symlink file")
    with tempfile.TemporaryDirectory(prefix="mioagent-verify-", dir="/var/tmp") as tmp:
        process = _gpg_process(["--decrypt", str(archive)], passphrase, Path(tmp) / "gnupg")
        observed: dict[str, dict] = {}
        supplied = None
        total = 0
        try:
            assert process.stdout is not None
            with tarfile.open(fileobj=process.stdout, mode="r|gz") as tf:
                for member in tf:
                    logical = _safe_archive_file(member)
                    if logical in observed or (logical == "manifest.json" and supplied is not None):
                        raise StorageError("Duplicate archive entry")
                    handle = tf.extractfile(member)
                    if handle is None:
                        raise StorageError("Missing archive payload")
                    digest = hashlib.sha256()
                    copied = 0
                    sink = None
                    if logical == "data/mioagent.db":
                        sink = (Path(tmp) / "mioagent.db").open("xb")
                    elif logical == "manifest.json":
                        sink = io.BytesIO()
                    try:
                        while block := handle.read(1024 * 1024):
                            copied += len(block)
                            total += len(block)
                            if total > maximum + 2_000_000:
                                raise StorageError("Archive exceeds verified restore budget")
                            digest.update(block)
                            if sink:
                                sink.write(block)
                    finally:
                        if sink and not isinstance(sink, io.BytesIO):
                            sink.close()
                        handle.close()
                    if copied != member.size:
                        raise StorageError("Truncated archive entry")
                    if logical == "manifest.json":
                        if not isinstance(sink, io.BytesIO):
                            raise StorageError("Manifest missing")
                        supplied = json.loads(sink.getvalue())
                    else:
                        observed[logical] = {"sha256": digest.hexdigest(), "size": copied}
            diagnostics = process.stderr.read().decode("utf-8", errors="replace")
            code = process.wait(timeout=120)
            if code != 0:
                raise StorageError(f"GPG authentication or decrypt failed (exit {code}): {diagnostics[:160]}")
            if not isinstance(supplied, dict) or supplied.get("schema") != SCHEMA:
                raise StorageError("Export manifest missing or incompatible")
            if supplied.get("excludes_credentials") is not True or supplied.get("files") != observed:
                raise StorageError("Encrypted export manifest does not match its files")
            if "data/mioagent.db" not in observed:
                raise StorageError("Snapshot database missing")
            with sqlite3.connect((Path(tmp) / "mioagent.db").as_uri() + "?mode=ro", uri=True) as db:
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise StorageError("Encrypted snapshot SQLite integrity failed")
            return {"verified": True, "files": len(observed), "sqlite_integrity": "ok",
                    "encryption": "GPG symmetric AES256"}
        except BaseException:
            if process.poll() is None:
                process.kill()
            process.wait()
            raise
        finally:
            if process.stdout:
                process.stdout.close()
