"""Owner-only, process-identity-checked persistent worker service.

Use python scripts/manage_work_worker.py {start,status,stop}. Never touch a
process identified solely by its PID file or an occupied TCP port.
"""
from __future__ import annotations

import argparse
import os
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
RUNTIME = Path(f"/var/tmp/mioagent-native-{os.getuid()}")
PID = RUNTIME / "work-worker.pid"
LOG = RUNTIME / "logs" / "work-worker.log"


def identified(pid: int) -> bool:
    try:
        proc = Path(f"/proc/{pid}")
        command = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        return (pid > 1 and proc.stat().st_uid == os.getuid()
                and Path(os.readlink(proc / "cwd")) == PROJECT
                and "-m mio.work_worker" in command
                and Path(os.readlink(proc / "exe")).name.startswith("python"))
    except (OSError, ValueError):
        return False


def current() -> int | None:
    if PID.is_symlink():
        raise RuntimeError("Refusing symlink worker PID")
    try:
        pid = int(PID.read_text().strip())
    except (OSError, ValueError):
        return None
    return pid if identified(pid) else None


def start() -> None:
    if current():
        print("Work worker: already running")
        return
    if not RUNTIME.is_dir() or not (RUNTIME / "work").is_dir():
        raise RuntimeError("Private MioAgent Work runtime unavailable")
    if RUNTIME.stat().st_uid != os.getuid() or stat.S_IMODE(RUNTIME.stat().st_mode) & 0o077:
        raise RuntimeError("Unsafe runtime permissions")
    if PID.exists() and not PID.is_symlink():
        PID.unlink()  # Stale PID file only, not its process
    # A standalone manager does not inherit the native API's settings.
    # Load only the verified private token and local model configuration.
    if __package__:
        from scripts.native_runtime import get_token, load_model_config
    else:
        from native_runtime import get_token, load_model_config

    worker_env = os.environ.copy()
    worker_env.update({
        "MIO_API_TOKEN": get_token(),
        "MIO_LOCAL_MODEL": "",
        "MIO_LOCAL_BASE_URL": "http://127.0.0.1:11434/v1",
        "MIO_MODEL_ROUTE": "local",
        "MIO_ALLOW_CLOUD": "false",
        "MIO_CLOUD_API_KEY": "",
    })
    worker_env.update(load_model_config())

    with LOG.open("ab", buffering=0) as log:
        proc = subprocess.Popen([sys.executable, "-m", "mio.work_worker"], cwd=PROJECT,
                                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                env=worker_env, start_new_session=True, close_fds=True)
    PID.write_text(f"{proc.pid}\n")
    PID.chmod(0o600)
    time.sleep(0.5)
    if not identified(proc.pid):
        raise RuntimeError("Work worker process did not remain alive; inspect work-worker.log")
    print(f"Work worker: running PID {proc.pid} independently of dashboard/API")


def stop() -> None:
    pid = current()
    if pid is None:
        print("Work worker: not managed/running")
        return
    os.kill(pid, signal.SIGTERM)
    for _ in range(20):
        if not identified(pid):
            PID.unlink(missing_ok=True)
            print("Work worker: stopped")
            return
        time.sleep(0.2)
    print("Work worker: stop requested; active model operation may need to finish")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "status", "stop"))
    args = parser.parse_args()
    try:
        if args.action == "start":
            start()
        elif args.action == "stop":
            stop()
        else:
            print("Work worker: running" if current() else "Work worker: stopped")
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"ERROR: {exc}") from exc


if __name__ == "__main__":
    main()
