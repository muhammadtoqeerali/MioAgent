"""Dedicated, non-browser Work queue consumer: no host shell/browser grants.

Runs existing bounded Work execute() in a separate process. Restarts preserve
queued tasks and mark abandoned running tasks interrupted, never completed.
A nonblocking private flock prevents duplicate workers on the same machine.
"""
from __future__ import annotations

import asyncio
import fcntl
import os
import signal
import stat
import time
from pathlib import Path

from mio.config import Settings
from mio.work_agent import execute
from mio.supervisor_core import advance_supervisor
from mio.work_core import RUNTIME, WorkStop, db, event, run_info, update

WORK_ROOT = RUNTIME / "work"


def reconcile(root: Path) -> int:
    """Only the exclusive-lock holder can reconcile after its predecessor died."""
    with db(root) as conn:
        now = int(time.time())
        rows = conn.execute("SELECT id FROM runs WHERE state='running'").fetchall()
        for item in rows:
            conn.execute("UPDATE runs SET state='interrupted',updated=?,error=? WHERE id=?",
                         (now, "Independent Work worker restarted; owner must explicitly retry", item["id"]))
            conn.execute("INSERT INTO events(run,phase,detail,created) VALUES (?,?,?,?)",
                         (item["id"], "interrupted", "Worker stopped before delivering verified outcome", now))
        return len(rows)


def pending(root: Path) -> str | None:
    with db(root) as conn:
        row = conn.execute("SELECT id FROM runs WHERE state='queued' ORDER BY created,id LIMIT 1").fetchone()
        return row["id"] if row else None


def private_lock(root: Path):
    if root.is_symlink():
        raise WorkStop("Worker store cannot be a symlink")
    with db(root):
        pass  # Validate private owner-only store before opening the lock.
    path = root / "work-worker.lock"
    if path.is_symlink():
        raise WorkStop("Worker lock is a symlink")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        os.close(fd)
        raise WorkStop("Unsafe worker lock")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise WorkStop("Another persistent Work worker is already active") from None
    return fd


async def serve(root: Path = WORK_ROOT, poll_seconds: float = 2.0) -> None:
    lock = private_lock(root)
    active = True

    def stop(_signum, _frame):
        nonlocal active
        active = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        interrupted = reconcile(root)
        print(f"MioAgent persistent worker ready; interrupted old runs={interrupted}", flush=True)
        settings = Settings()
        while active:
            advance_supervisor(root)
            run_id = pending(root)
            if run_id:
                print(f"Executing queued Work run {run_id[:8]}", flush=True)
                try:
                    result = await execute(root, run_id, settings)
                    print(f"Work run {run_id[:8]} ended as {result['state']}", flush=True)
                except Exception as exc:  # noqa: BLE001 - ensure unexpected failures reach SQLite
                    print(f"Work queue failure {run_id[:8]}: {type(exc).__name__}", flush=True)
                    try:
                        previous = run_info(root, run_id)
                        if previous["state"] in ("queued", "running"):
                            event(root, run_id, "error", f"Worker failure: {type(exc).__name__}")
                            update(root, run_id, "failed", error="Worker could not complete this job")
                    except (OSError, ValueError, RuntimeError) as recovery_exc:
                        print(f"Work audit update failed: {type(recovery_exc).__name__}", flush=True)
                continue
            await asyncio.sleep(poll_seconds)
    finally:
        os.close(lock)


def main() -> None:
    try:
        asyncio.run(serve())
    except (WorkStop, OSError, RuntimeError) as exc:
        raise SystemExit(f"ERROR: persistent Work worker: {exc}") from exc


if __name__ == "__main__":
    main()
