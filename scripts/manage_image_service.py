"""Local installed ComfyUI manager; no downloads and no host-wide process kills.

Running the image backend is separate from choosing/buying model weights. Existing
SD1.5 remains installed; checkpoint upgrades require explicit owner approval.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import stat
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

PROJECT = Path(__file__).resolve().parents[1]
RUNTIME = Path(f"/var/tmp/mioagent-native-{os.getuid()}")
ROOT = Path.home() / ".cache/mioagent/comfyui"
APP = ROOT / "ComfyUI"
PY = ROOT / "venv/bin/python"
CHECKPOINT = APP / "models/checkpoints/v1-5-pruned-emaonly-fp16.safetensors"
PID = RUNTIME / "image-backend.pid"
LOG = RUNTIME / "logs/image-backend.log"
ENDPOINT = "http://127.0.0.1:8188/object_info/CheckpointLoaderSimple"


def healthy() -> bool:
    try:
        with urlopen(ENDPOINT, timeout=3) as result:
            info = json.load(result)
            return result.status == 200 and "CheckpointLoaderSimple" in info
    except (OSError, URLError, ValueError, KeyError):
        return False


def identified(pid: int) -> bool:
    try:
        p = Path(f"/proc/{pid}")
        cmd = (p / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        return (pid > 1 and p.stat().st_uid == os.getuid()
                and Path(os.readlink(p / "cwd")) == APP
                and "main.py" in cmd and "--port 8188" in cmd
                and str(PY) in cmd)
    except (OSError, ValueError):
        return False


def pid() -> int | None:
    if PID.is_symlink():
        raise RuntimeError("Unsafe image backend PID file")
    try:
        candidate = int(PID.read_text().strip())
    except (OSError, ValueError):
        return None
    return candidate if identified(candidate) else None


def ready_files() -> bool:
    # venv/bin/python normally links to python3 or a trusted system interpreter.
    # The executable must exist and be runnable; source/model files stay non-links.
    main = APP / "main.py"
    if not main.is_file() or main.is_symlink():
        return False
    if not PY.is_file() or not os.access(PY, os.X_OK):
        return False
    if not CHECKPOINT.is_file() or CHECKPOINT.is_symlink():
        return False
    return CHECKPOINT.stat().st_size > 1_000_000_000


def port_busy() -> bool:
    proc = subprocess.run(["ss", "-H", "-ltn", "sport = :8188"],
                          capture_output=True, text=True, check=True, timeout=6)
    return bool(proc.stdout.strip())


def start() -> None:
    if healthy():
        print("ComfyUI: already healthy on loopback; no new process launched")
        return
    if pid():
        print("ComfyUI: managed process is booting; consult logs")
        return
    if port_busy():
        raise RuntimeError("Port 8188 occupied by non-healthy process; no process touched")
    if not ready_files():
        print("ComfyUI: not installed/configured; no download or modification performed")
        return
    if not RUNTIME.is_dir() or not (RUNTIME / "logs").is_dir():
        raise RuntimeError("Private MioAgent runtime unavailable")
    if RUNTIME.stat().st_uid != os.getuid() or stat.S_IMODE(RUNTIME.stat().st_mode) & 0o077:
        raise RuntimeError("Private runtime permissions invalid")
    if PID.exists() and not PID.is_symlink():
        PID.unlink()
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = "1"  # Existing second RTX 4090 convention
    with LOG.open("ab", buffering=0) as log:
        process = subprocess.Popen([str(PY), "main.py", "--listen", "127.0.0.1", "--port", "8188"],
                                   cwd=APP, env=env, stdout=log, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, close_fds=True, start_new_session=True)
    PID.write_text(f"{process.pid}\n")
    PID.chmod(0o600)
    print(f"ComfyUI: managed launch requested PID {process.pid}; GPU 1 (second GPU)")
    for _ in range(40):
        if healthy():
            print("ComfyUI: healthy; Studio image capability should become ready")
            return
        if not identified(process.pid):
            raise RuntimeError("ComfyUI exited before becoming ready; inspect image-backend.log")
        time.sleep(2)
    print("ComfyUI: still booting; check status and image-backend.log")


def stop() -> None:
    p = pid()
    if p is None:
        print("ComfyUI: no identified managed process; nothing signaled")
        return
    os.kill(p, signal.SIGTERM)
    print("ComfyUI: stop requested for identified managed process")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("start", "status", "stop"))
    args = ap.parse_args()
    try:
        if args.action == "status":
            print(f"ComfyUI: healthy={healthy()} managed={pid() is not None} installed={ready_files()}")
        elif args.action == "start":
            start()
        else:
            stop()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"ERROR: ComfyUI manager: {exc}") from exc


if __name__ == "__main__":
    main()
