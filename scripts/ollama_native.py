"""User-owned Ollama runtime: start/status/pull/stop without sudo or Docker.

The model service always binds 127.0.0.1:11434. Model weights live OUTSIDE
MioAgent's Git repository. Only a verified process started by this helper
can be stopped; existing services not owned by this helper are left alone.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import socket
import stat
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

RUNTIME = Path(f"/var/tmp/mioagent-ollama-{os.getuid()}")
PROJECT = Path(__file__).resolve().parents[1]
MODEL_DIR = Path(os.environ.get("MIO_OLLAMA_MODELS_DIR", str(Path.home() / "MioAgentModels")))
URL = "http://127.0.0.1:11434"
MODEL_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
USER_INSTALL = Path(f"/var/tmp/mioagent-ollama-binaries-{os.getuid()}")


def setup() -> None:
    result = subprocess.run(
        ["findmnt", "-no", "FSTYPE", "-T", str(RUNTIME.parent)],
        check=True, capture_output=True, text=True,
    )
    if result.stdout.strip() not in {"ext4", "xfs", "btrfs", "zfs", "f2fs"}:
        raise RuntimeError("Ollama runtime credentials require a native Linux filesystem")
    if RUNTIME.is_symlink():
        raise RuntimeError("Refusing symlink runtime directory")
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    s = RUNTIME.stat()
    if s.st_uid != os.getuid() or stat.S_IMODE(s.st_mode) & 0o077:
        raise RuntimeError("Ollama runtime directory is not private")


def binary() -> str:
    """Prefer the pinned, user-owned Ollama runtime over the older system binary.

    Never follow a user-runtime symlink outside the owner-private installation root.
    """
    root = USER_INSTALL
    if root.exists():
        st = root.lstat()
        if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid()
                or stat.S_IMODE(st.st_mode) & 0o077):
            raise RuntimeError("User Ollama binary directory is not private")
        candidate = root / "current" / "bin" / "ollama"
        if candidate.exists():
            resolved = candidate.resolve(strict=True)
            if not resolved.is_relative_to(root.resolve(strict=True)):
                raise RuntimeError("User Ollama binary escapes private directory")
            bst = resolved.stat()
            if (not stat.S_ISREG(bst.st_mode) or bst.st_uid != os.getuid()
                    or not os.access(resolved, os.X_OK)):
                raise RuntimeError("Invalid user-owned Ollama executable")
            return str(candidate)
    result = shutil.which("ollama")
    if result is None:
        raise RuntimeError("Ollama is not installed or not on PATH")
    return result


def tags() -> dict | None:
    try:
        with urlopen(f"{URL}/api/tags", timeout=3) as response:
            if response.status != 200:
                return None
            result = json.loads(response.read(65536).decode("utf-8"))
            return result if isinstance(result, dict) else None
    except (OSError, HTTPError, URLError, ValueError):
        return None


def owned_pid() -> int | None:
    try:
        pid = int((RUNTIME / "ollama.pid").read_text().strip())
        if pid < 1:
            return None
        proc = Path(f"/proc/{pid}")
        if proc.stat().st_uid != os.getuid() or Path(os.readlink(proc / "cwd")) != PROJECT:
            return None
        command = (proc / "cmdline").read_bytes().split(b"\0")
        if not command or b"serve" not in command[1:]:
            return None
        expected = binary()
        if not os.path.samefile(proc / "exe", expected):
            return None
        os.kill(pid, 0)
        return pid
    except (ValueError, OSError, FileNotFoundError):
        return None


def start() -> None:
    setup()
    if tags() is not None:
        print("Ollama already responds on loopback; leaving existing service unchanged.")
        return
    if owned_pid() is not None:
        raise RuntimeError("Owned Ollama process exists but is not responding; check its log")
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", 11434))
        except OSError as exc:
            raise RuntimeError("Port 11434 is occupied; refusing to replace its process") from exc
    executable = binary()
    # Deliberately avoid ~/.ollama inside the source repository. NTFS-backed
    # model weights should be treated as untrusted if multiple users share it.
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({"OLLAMA_HOST": "127.0.0.1:11434", "OLLAMA_MODELS": str(MODEL_DIR)})
    with (RUNTIME / "ollama.log").open("ab", buffering=0) as log:
        proc = subprocess.Popen(
            [executable, "serve"], cwd=PROJECT, env=env,
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            close_fds=True, start_new_session=True,
        )
    (RUNTIME / "ollama.pid").write_text(f"{proc.pid}\n")
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if tags() is not None:
            print(f"Ollama running at {URL}; process {proc.pid}")
            print(f"Model weights directory: {MODEL_DIR}")
            return
        if proc.poll() is not None:
            break
        time.sleep(0.5)
    print("Recent Ollama logs:")
    path = RUNTIME / "ollama.log"
    print("\n".join(path.read_text(errors="replace").splitlines()[-30:]))
    raise RuntimeError("Ollama failed to start; model download was not attempted")


def status() -> None:
    setup()
    result = tags()
    print("Ollama API:", "reachable" if result is not None else "unavailable")
    print("Managed service:", "running" if owned_pid() is not None else "not managed")
    if result is not None:
        print("Downloaded models:")
        for model in result.get("models", [])[:30]:
            if isinstance(model, dict):
                print(" -", model.get("name", "(unknown)"))
    print("Weights directory for managed service:", MODEL_DIR)


def pull(model: str) -> None:
    if not MODEL_NAME_RE.fullmatch(model):
        raise RuntimeError("Invalid model identifier")
    if tags() is None:
        raise RuntimeError("Ollama is not reachable; start it first")
    env = os.environ.copy()
    env["OLLAMA_HOST"] = "127.0.0.1:11434"
    # User-requested model download, potentially several GB.
    subprocess.run([binary(), "pull", model], check=True, env=env)


def stop() -> None:
    setup()
    pid = owned_pid()
    if pid is None:
        print("No verifiable Ollama service started by MioAgent; nothing stopped")
        return
    print(f"Stopping managed Ollama process {pid}")
    os.killpg(pid, signal.SIGTERM)
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and owned_pid() is not None:
        time.sleep(0.2)
    if owned_pid() is not None:
        raise RuntimeError("Ollama is still stopping; inspect the log")
    (RUNTIME / "ollama.pid").unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "status", "pull", "stop"])
    parser.add_argument("model", nargs="?", default="")
    args = parser.parse_args()
    try:
        if args.action == "start":
            start()
        elif args.action == "status":
            status()
        elif args.action == "stop":
            stop()
        elif args.action == "pull":
            if not args.model:
                parser.error("pull requires a model identifier")
            pull(args.model)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
