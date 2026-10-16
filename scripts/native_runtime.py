"""Run MioAgent natively without Docker or administrator privileges.

Run as: python3 scripts/native_runtime.py {start,status,smoke,logs,stop}

Only explicitly implemented task types can execute. Binds servers to localhost.
Credentials and SQLite database live in a private native-Linux directory.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import secrets
import signal
import stat
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT = Path(__file__).resolve().parents[1]
DASHBOARD = PROJECT / "apps" / "dashboard"
RUNTIME = Path(f"/var/tmp/mioagent-native-{os.getuid()}")
API_URL = "http://127.0.0.1:8000"
DASH_URL = "http://127.0.0.1:3000"
ALLOWED_FS = {"ext4", "xfs", "btrfs", "zfs", "f2fs"}
PROCESSES = {
    "api": "mio.api:create_app",
    "dashboard": str(DASHBOARD / "node_modules" / "next" / "dist" / "bin" / "next"),
}


def filesystem_type(path: Path) -> str:
    result = subprocess.run(
        ["findmnt", "-n", "-o", "FSTYPE", "-T", str(path)],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def private_dir(path: Path) -> Path:
    """Create/verify a secure directory, refusing symlinks and foreign ownership."""
    if path.is_symlink():
        raise RuntimeError(f"Refusing symlink: {path}")
    if path.exists():
        st = path.stat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
            raise RuntimeError(f"Directory is not owned by this user: {path}")
        if stat.S_IMODE(st.st_mode) & 0o077:
            raise RuntimeError(f"Directory is accessible to other users: {path}")
    else:
        path.mkdir(mode=0o700)
    return path


def setup_runtime() -> None:
    fstype = filesystem_type(RUNTIME.parent)
    if fstype not in ALLOWED_FS:
        raise RuntimeError(f"{RUNTIME.parent} uses {fstype}, not a supported native Linux FS")
    private_dir(RUNTIME)
    private_dir(RUNTIME / "data")
    private_dir(RUNTIME / "logs")


def get_token(create: bool = False) -> str:
    path = RUNTIME / "api-token"
    if not path.exists():
        if not create:
            raise RuntimeError("No API token. Start the native runtime first.")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(secrets.token_urlsafe(48) + "\n")
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
        raise RuntimeError("Invalid API credential file")
    if stat.S_IMODE(st.st_mode) & 0o077:
        raise RuntimeError("API credential permissions too broad")
    token = path.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise RuntimeError("Invalid API credential")
    return token


MODEL_CONFIG_KEYS = frozenset({
    "MIO_LOCAL_MODEL", "MIO_LOCAL_BASE_URL", "MIO_MODEL_ROUTE", "MIO_ALLOW_CLOUD",
})
MODEL_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")


def load_model_config() -> dict[str, str]:
    """Read explicit local-only model settings from an owner-private, non-symlink file.

    Never source a shell file or accept cloud credentials from this file. The
    configuration script writes the same four keys. Missing file means that
    AI inference is intentionally disabled until configuration is completed.
    """
    config = RUNTIME / "model.env"
    try:
        fd = os.open(config, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return {}
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise RuntimeError("Untrusted model configuration file")
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise RuntimeError("Model configuration is accessible to other users")
        if info.st_size > 4096:
            raise RuntimeError("Model configuration is unexpectedly large")
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            fd = -1
            data = handle.read(4097)
    finally:
        if fd >= 0:
            os.close(fd)
    if len(data) > 4096:
        raise RuntimeError("Model configuration is unexpectedly large")
    parsed: dict[str, str] = {}
    for line in data.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if separator != "=" or key not in MODEL_CONFIG_KEYS or key in parsed:
            raise RuntimeError("Model configuration contains an unsupported or repeated key")
        parsed[key] = value.strip()
    if parsed.get("MIO_LOCAL_MODEL") and not MODEL_NAME_RE.fullmatch(
        parsed["MIO_LOCAL_MODEL"]
    ):
        raise RuntimeError("Invalid local model identifier")
    if parsed.get("MIO_LOCAL_BASE_URL", "http://127.0.0.1:11434/v1") != (
        "http://127.0.0.1:11434/v1"
    ):
        raise RuntimeError("Model endpoint must remain on the approved loopback URL")
    if parsed.get("MIO_MODEL_ROUTE", "local") != "local":
        raise RuntimeError("Only local model routing is enabled in this deployment")
    if parsed.get("MIO_ALLOW_CLOUD", "false").lower() != "false":
        raise RuntimeError("Cloud calls are disabled in this deployment")
    return parsed


@contextmanager
def single_instance():
    lock_path = RUNTIME / "runtime.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield


def pid_path(role: str) -> Path:
    return RUNTIME / f"{role}.pid"


def command_for_pid(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(
            errors="replace"
        )
    except (OSError, ValueError):
        return ""


def is_our_process(role: str, pid: int) -> bool:
    """Verify PID ownership, working directory and executable before managing a service.

    Next.js may rename the Node process to ``next-server (v...)`` after startup.
    Matching the original command alone falsely reports that process as stopped.
    Never match an unrelated process merely because it listens on our port.
    """
    if pid < 1 or role not in PROCESSES:
        return False
    proc = Path(f"/proc/{pid}")
    expected_cwd = PROJECT if role == "api" else DASHBOARD
    try:
        if proc.stat().st_uid != os.getuid():
            return False
        if Path(os.readlink(proc / "cwd")) != expected_cwd:
            return False
        command = command_for_pid(pid)
        if not command:
            return False
        if role == "api":
            return PROCESSES["api"] in command
        if PROCESSES["dashboard"] in command:
            return True
        # Node/Next.js changes its process title *after* the server starts.
        # Still require a PID we recorded, the correct cwd, uid and Node binary.
        if not command.startswith("next-server"):
            return False
        executable = Path(os.readlink(proc / "exe")).name
        return executable in {"node", "nodejs"}
    except (OSError, ValueError):
        return False


def read_pid(role: str) -> int | None:
    try:
        return int(pid_path(role).read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return None


def is_running(role: str) -> bool:
    pid = read_pid(role)
    return pid is not None and is_our_process(role, pid)


def port_listeners(port: int) -> str:
    """Return genuine TCP LISTEN sockets, not connection TIME_WAIT records.

    A bind() test without SO_REUSEADDR can incorrectly report a busy port
    immediately after a Next.js restart. `ss -ltn` queries LISTEN state
    directly; it never sends a signal or changes firewall/socket settings.
    """
    if not 1 <= port <= 65535:
        raise ValueError("Invalid TCP port")
    result = subprocess.run(
        ["ss", "-H", "-ltnp", f"sport = :{port}"],
        check=True, capture_output=True, text=True, timeout=8,
    )
    return result.stdout.strip()


def port_available(port: int) -> bool:
    return not port_listeners(port)


def load_json(url: str, token: str | None = None, data: dict | None = None) -> dict:
    headers = {"Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    payload = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        payload = json.dumps(data).encode("utf-8")
    with urlopen(Request(url, data=payload, headers=headers), timeout=4) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for(url: str, timeout: float = 40) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return True
        except (OSError, HTTPError, URLError):
            pass
        time.sleep(0.5)
    return False


def start_service(role: str, command: list[str], cwd: Path, environ: dict[str, str]) -> None:
    logfile = (RUNTIME / "logs" / f"{role}.log").open("ab", buffering=0)
    try:
        proc = subprocess.Popen(
            command, cwd=cwd, env=environ, stdin=subprocess.DEVNULL,
            stdout=logfile, stderr=subprocess.STDOUT,
            start_new_session=True, close_fds=True,
        )
    finally:
        logfile.close()
    pid_path(role).write_text(f"{proc.pid}\n", encoding="utf-8")
    print(f"  {role}: process {proc.pid} started")


def stop_service(role: str) -> None:
    pid = read_pid(role)
    if pid is None:
        return
    if not is_our_process(role, pid):
        print(f"  {role}: PID file is stale or unrecognized; not signaling it")
        pid_path(role).unlink(missing_ok=True)
        return
    print(f"  {role}: stopping process {pid}")
    try:
        if os.getpgid(pid) == pid:
            os.killpg(pid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if not is_our_process(role, pid):
            break
        time.sleep(0.2)
    if is_our_process(role, pid):
        print(f"  {role}: still stopping; inspect its logs")
    else:
        pid_path(role).unlink(missing_ok=True)


def start() -> None:
    setup_runtime()
    with single_instance():
        if is_running("api") or is_running("dashboard"):
            print("A MioAgent native service is already running. Use 'status' or 'stop'.")
            raise SystemExit(1)
        for port in (8000, 3000):
            listeners = port_listeners(port)
            if listeners:
                raise RuntimeError(
                    f"Port {port} has an active TCP listener. "
                    "It will NOT be stopped automatically.\n" + listeners
                )
        python = Path.home() / ".cache" / "mioagent" / "phase1-venv" / "bin" / "python"
        next_bin = DASHBOARD / "node_modules" / "next" / "dist" / "bin" / "next"
        build_id = DASHBOARD / ".next" / "BUILD_ID"
        if not python.is_file():
            raise RuntimeError(f"Missing tested Python venv: {python}")
        if not next_bin.is_file() or not build_id.is_file():
            raise RuntimeError("Dashboard is not built. Run npm install and npm run build first.")
        node = subprocess.run(
            ["which", "node"], capture_output=True, text=True, check=True
        ).stdout.strip()
        if not node:
            raise RuntimeError("Node.js binary was not found")
        token = get_token(create=True)
        env = os.environ.copy()
        # Explicit defaults prevent inherited shell variables from enabling
        # cloud requests or silently selecting a different provider.
        env.update({
            "MIO_API_TOKEN": token,
            "MIO_DATABASE_URL": f"sqlite+pysqlite:///{RUNTIME / 'data' / 'mioagent.db'}",
            "MIO_WORKSPACE_ROOT": str(PROJECT),
            "MIO_API_URL": API_URL,
            "MIO_POLL_SECONDS": "1",
            "MIO_LOCAL_MODEL": "",
            "MIO_LOCAL_BASE_URL": "http://127.0.0.1:11434/v1",
            "MIO_MODEL_ROUTE": "local",
            "MIO_ALLOW_CLOUD": "false",
            "MIO_CLOUD_API_KEY": "",
        })
        # Project Mode requires a manually enabled owner-private flag. Never trust
        # inherited MIO_ENABLE_PROJECT_MODE / MIO_PROJECT_ROOT environment values.
        marker = RUNTIME / "project-mode-enabled"
        feature_enabled = False
        if marker.exists() or marker.is_symlink():
            info = marker.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) & 0o077
                    or marker.read_text(encoding="utf-8") != "enabled\n"):
                raise RuntimeError("Project Mode flag must be an owner-private approved file")
            feature_enabled = True
        env.update({
            "MIO_ENABLE_PROJECT_MODE": "true" if feature_enabled else "false",
            "MIO_PROJECT_ROOT": str(RUNTIME / "projects"),
        })
        # Fix: previously configure_model.py wrote model.env but no process
        # actually loaded it. The supervisor therefore stayed unconfigured.
        env.update(load_model_config())
        print("Starting locally on 127.0.0.1 (no Docker / no sudo)...")
        start_service(
            "api", [str(python), "-m", "uvicorn", "mio.api:create_app", "--factory",
                    "--host", "127.0.0.1", "--port", "8000"], PROJECT, env,
        )
        if not wait_for(f"{API_URL}/health", timeout=35):
            stop_service("api")
            raise RuntimeError("API did not start; read logs with 'logs'")
        start_service(
            "dashboard", [node, str(next_bin), "start", "--hostname", "127.0.0.1",
                          "--port", "3000"], DASHBOARD, env,
        )
        if not wait_for(DASH_URL, timeout=45):
            stop_service("dashboard")
            stop_service("api")
            raise RuntimeError("Dashboard did not start; read logs with 'logs'")
        try:
            status = load_json(f"{DASH_URL}/api/proxy/status")
            assert status["version"] == "0.2.0"
        except (OSError, HTTPError, URLError, AssertionError, KeyError, ValueError) as exc:
            stop_service("dashboard")
            stop_service("api")
            raise RuntimeError("Dashboard proxy failed authentication to API") from exc
        print("\nSUCCESS: native MioAgent services are running")
        print("  Dashboard:", DASH_URL)
        print("  API health:", f"{API_URL}/health")
        print("  Runtime data:", RUNTIME)
        model = env.get("MIO_LOCAL_MODEL")
        print("  AI model configured:", model or "no (use configure_model.py)")
        print("  Local model service: independently verify Ollama is running")
        print("  Note: voice and computer-control agents are not implemented yet")


def status() -> None:
    if not RUNTIME.exists():
        print("No native runtime initialized")
        return
    setup_runtime()
    for role in PROCESSES:
        print(f"{role}: {'running' if is_running(role) else 'not running'}")
    for name, url in (("api", f"{API_URL}/health"), ("dashboard", DASH_URL)):
        try:
            with urlopen(url, timeout=2) as response:
                print(f"{name} HTTP: {response.status}")
                if not is_running(name):
                    print(f"  WARNING: {name} serves HTTP, but its recorded PID is not recognized.")
                    print("  Do not kill the port occupant without identifying its process.")
        except (OSError, HTTPError, URLError):
            print(f"{name} HTTP: unavailable")
    print("Runtime:", RUNTIME)


def smoke() -> None:
    setup_runtime()
    token = get_token()
    result = load_json(f"{API_URL}/health")
    if result.get("ok") is not True:
        raise RuntimeError("API health failed")
    data = load_json(f"{API_URL}/api/status", token)
    if data.get("version") != "0.2.0":
        raise RuntimeError("Unexpected API version")
    proxied = load_json(f"{DASH_URL}/api/proxy/status")
    if proxied.get("version") != "0.2.0":
        raise RuntimeError("Dashboard proxy cannot access API")
    test_text = "MioAgent native runtime smoke test"
    new = load_json(f"{API_URL}/api/tasks", token, {"kind": "echo", "prompt": test_text})
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        task = load_json(f"{API_URL}/api/tasks/{new['id']}", token)
        if task["status"] == "completed":
            if task["result"]["text"] != test_text:
                raise RuntimeError("Echo result is incorrect")
            break
        if task["status"] == "failed":
            raise RuntimeError(f"Task failed: {task['error']}")
        time.sleep(0.5)
    else:
        raise RuntimeError("Timed out waiting for echo task")
    tasks = load_json(f"{API_URL}/api/tasks", token)
    if new["id"] not in {task["id"] for task in tasks["tasks"]}:
        raise RuntimeError("Task was not persisted")
    print("PASS: API health, bearer authentication, Next.js proxy,")
    print("      SQLite persistence, background worker, and task results")


def logs() -> None:
    setup_runtime()
    for role in PROCESSES:
        path = RUNTIME / "logs" / f"{role}.log"
        print(f"\n=== {role.upper()} LOG (last 50 lines) ===")
        if not path.is_file():
            print("No log file")
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        print("\n".join(lines[-50:]) or "(empty)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "status", "smoke", "logs", "stop"])
    args = parser.parse_args()
    try:
        if args.action == "start":
            start()
        elif args.action == "status":
            status()
        elif args.action == "smoke":
            smoke()
        elif args.action == "logs":
            logs()
        elif args.action == "stop":
            setup_runtime()
            with single_instance():
                stop_service("dashboard")
                stop_service("api")
            status()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"ERROR: {exc}") from exc


if __name__ == "__main__":
    main()
