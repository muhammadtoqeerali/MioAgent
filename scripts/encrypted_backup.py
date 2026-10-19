"""Operator-controlled local encrypted backups for a Windows -> KIOS VPN relay.

Creates only ciphertext outside the private native runtime; never connects to KIOS.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from mio.durable_storage import StorageError
from mio.encrypted_export import export_encrypted, verify_encrypted
from scripts.native_runtime import RUNTIME, is_running


def _password(confirmed: bool) -> str:
    password = getpass.getpass("Backup encryption passphrase (not displayed): ")
    if confirmed and password != getpass.getpass("Repeat passphrase: "):
        raise StorageError("Passphrases do not match")
    if len(password) < 16:
        raise StorageError("Passphrase must contain at least 16 characters")
    return password


def _no_active_jobs() -> None:
    database = RUNTIME / "data" / "mioagent.db"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        active = db.execute(
            "SELECT COUNT(*) FROM tasks WHERE status IN ('queued', 'running')"
        ).fetchone()[0]
    if active:
        raise StorageError(f"Refusing to stop {active} active or queued tasks")


def _native(action: str) -> None:
    subprocess.run(
        [sys.executable, "scripts/native_runtime.py", action],
        check=True, timeout=130,
    )


def create(output: Path, max_mib: int) -> dict:
    if not (is_running("api") and is_running("dashboard")):
        raise StorageError("Expected both managed services running; do not stop unknown processes")
    _no_active_jobs()
    password = _password(True)
    # Password received before stopping the local UI, minimizing downtime.
    stopped = False
    primary_error = None
    try:
        stopped = True
        _native("stop")
        if is_running("api") or is_running("dashboard"):
            raise StorageError("Native services did not stop cleanly")
        result = export_encrypted(RUNTIME, output, password, max_mib)
        verified = verify_encrypted(output, password, max_mib)
        result["verification"] = verified
        return result
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        if stopped:
            try:
                _native("start")
                _native("smoke")
            except BaseException as restart_error:
                if primary_error is not None:
                    raise StorageError(
                        "Backup failed AND services could not restart; inspect runtime status/logs"
                    ) from restart_error
                raise StorageError("Backup complete but service restart/smoke failed") from restart_error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    create_parser = sub.add_parser("create", help="Stop, export, verify, restart")
    create_parser.add_argument("--output", required=True, type=Path)
    create_parser.add_argument("--max-mib", type=int, default=2048)
    verify_parser = sub.add_parser("verify", help="Decrypt and verify without restoring")
    verify_parser.add_argument("--input", required=True, type=Path)
    verify_parser.add_argument("--max-mib", type=int, default=2048)
    args = parser.parse_args()
    try:
        if args.action == "create":
            result = create(args.output, args.max_mib)
        else:
            result = verify_encrypted(args.input, _password(False), args.max_mib)
    except (StorageError, OSError, sqlite3.Error, subprocess.SubprocessError) as exc:
        parser.exit(1, f"STOP: {exc}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
