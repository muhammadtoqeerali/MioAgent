"""Fail-closed, review-triggered local unittest execution in a Bubblewrap sandbox.

Only approved project bytes are copied; no generated shell commands are executed.
This is an experimental verifier, not a comprehensive security certification.
"""

from __future__ import annotations

import json
import os
import re
import selectors
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from mio.project_mode import (
    MAX_TOTAL_BYTES,
    ProjectPolicyError,
    check_private_root,
    validate_draft,
    verify_existing_project,
)

OUTPUT_LIMIT = 32 * 1024
WALL_SECONDS = 30
MAX_TEST_FILES = 6
TRUSTED_PYTHON = Path("/usr/bin/python3")
TRUSTED_BWRAP = Path("/usr/bin/bwrap")

# Runs INSIDE unprivileged user/mount/PID/network namespaces. The entire
# filesystem is read-only, including /tmp and /dev; source is read-only.
# Resource limits are set before importing any project code.
HARNESS = """
import os, resource, sys, unittest
resource.setrlimit(resource.RLIMIT_CPU, (12, 13))
resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024 * 1024, 2 * 1024 * 1024))
resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
resource.setrlimit(resource.RLIMIT_NPROC, (1, 1))
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
suite = unittest.defaultTestLoader.discover('/work', pattern='test_*.py', top_level_dir='/work')
result = unittest.TextTestRunner(verbosity=1, stream=sys.stdout).run(suite)
print('MIO_VERIFIER_TESTS_RUN=' + str(result.testsRun), flush=True)
sys.exit(0 if result.wasSuccessful() and result.testsRun > 0 else 1)
""".strip()

PREFLIGHT = """
import os, socket
assert not os.path.exists('/home')
assert not os.path.exists('/mnt')
assert not os.path.exists('/var/tmp')
# Require a genuinely read-only mount at every sandbox-visible writable target.
# This is not a user-permissions test: statvfs checks the mounted filesystem.
for mount in ('/', '/tmp', '/dev', '/proc', '/work'):
    assert os.statvfs(mount).f_flag & os.ST_RDONLY, mount + ' is writable'
s = socket.socket()
try:
    assert s.connect_ex(('127.0.0.1', 8000)) != 0
finally:
    s.close()
print('MIO_SANDBOX_PREFLIGHT_OK')
""".strip()


class SandboxUnavailable(RuntimeError):
    """No verified OS isolation is available; refuse to execute."""


def sandbox_binary() -> tuple[str, str]:
    """Require exact admin-installed system executables, not PATH lookalikes."""
    for path in (TRUSTED_BWRAP, TRUSTED_PYTHON):
        resolved = path.resolve()
        if not path.is_file() or not resolved.is_relative_to(Path("/usr")):
            raise SandboxUnavailable(f"Required system executable unavailable: {path}")
        info = resolved.stat()
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise SandboxUnavailable(f"System executable is not trusted: {path}")
    # Ubuntu may configure /usr/bin/python3 -> /etc/alternatives/python3
    # -> /usr/bin/python3.10. The sandbox deliberately does not mount /etc:
    # invoke the root-owned, validated real binary already under /usr.
    # Resolve Bubblewrap as well to avoid a post-validation PATH/symlink alias.
    return (str(TRUSTED_BWRAP.resolve(strict=True)),
            str(TRUSTED_PYTHON.resolve(strict=True)))


def sandbox_argv(staging: Path, code: str) -> list[str]:
    """No host home, project root, private runtime, devices, or network mounted."""
    bwrap, python = sandbox_binary()
    if not staging.is_dir() or staging.is_symlink():
        raise SandboxUnavailable("Sandbox staging directory is invalid")
    return [
        bwrap, "--die-with-parent", "--new-session", "--unshare-user", "--unshare-pid",
        "--unshare-ipc", "--unshare-uts", "--unshare-net", "--cap-drop", "ALL",
        "--clearenv", "--setenv", "PATH", "/usr/bin:/bin",
        "--setenv", "HOME", "/work", "--setenv", "TMPDIR", "/tmp",
        "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
        "--tmpfs", "/", "--ro-bind", "/usr", "/usr",
        "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/lib64", "/lib64",
        "--ro-bind", str(staging), "/work",
        # Old distro Bubblewrap builds may not support --size. Instead of a
        # potentially unbounded writable tmpfs, the entire sandbox is
        # read-only. Tests requiring a writable /tmp will fail explicitly.
        "--dir", "/tmp", "--proc", "/proc", "--dev", "/dev",
        "--remount-ro", "/proc", "--remount-ro", "/dev",
        "--remount-ro", "/",
        "--chdir", "/work", "--hostname", "mio-verifier", "--",
        python, "-I", "-B", "-c", code,
    ]


def _bounded_run(argv: list[str], *, seconds: int = WALL_SECONDS) -> tuple[int, str, bool, bool]:
    """Bound total captured output and elapsed time; kill namespace on violations."""
    child = subprocess.Popen(
        argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd="/", env={"PATH": "/usr/bin:/bin"}, start_new_session=True,
        close_fds=True,
    )
    assert child.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(child.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + seconds
    chunks: list[bytes] = []
    captured = 0
    timed_out = False
    output_exceeded = False
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            for key, _ in selector.select(timeout=min(remaining, 0.25)):
                buf = os.read(key.fileobj.fileno(), 4096)
                if not buf:
                    selector.unregister(key.fileobj)
                    break
                captured += len(buf)
                if captured > OUTPUT_LIMIT:
                    chunks.append(buf[:max(0, OUTPUT_LIMIT - (captured - len(buf)))])
                    output_exceeded = True
                    break
                chunks.append(buf)
            if output_exceeded:
                break
            if child.poll() is not None and not selector.get_map():
                break
    finally:
        if child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        child.wait(timeout=5)
        selector.close()
        child.stdout.close()
    output = b"".join(chunks).decode("utf-8", errors="replace")
    return child.returncode, output, timed_out, output_exceeded


def preflight(root: Path) -> dict[str, Any]:
    """On the workstation, prove the actual Bubblewrap invocation works or fail."""
    secure = check_private_root(root)
    with tempfile.TemporaryDirectory(dir=secure, prefix=".mio-probe-") as scratch:
        path = Path(scratch)
        os.chmod(path, 0o700)
        code, log, timed_out, overflow = _bounded_run(sandbox_argv(path, PREFLIGHT), seconds=10)
    if code != 0 or timed_out or overflow or "MIO_SANDBOX_PREFLIGHT_OK" not in log:
        raise SandboxUnavailable("Sandbox self-test failed; no project executed: " + log[-500:])
    return {"sandbox": "bubblewrap", "preflight": "passed", "network": "unshared",
            "filesystem": "read_only"}


def _test_files(draft: dict[str, Any]) -> list[str]:
    return [item["path"] for item in draft["files"]
            if item["path"].endswith(".py") and Path(item["path"]).name.startswith("test_")]


def verify_approved_project(root: Path, project_id: str, draft: dict[str, Any]) -> dict[str, Any]:
    """Verify approved bytes then run stdlib unittest in private ephemeral sandbox.

    Does not modify the approved artifact, invoke a shell, install deps, or use GPU.
    """
    secure = check_private_root(root)
    checked = validate_draft(json.dumps({"plan": draft["plan"], "files": draft["files"]}))
    verified = verify_existing_project(secure, project_id, checked)
    if verified is None:
        raise ProjectPolicyError("Approved artifact is missing")
    if checked["total_bytes"] > MAX_TOTAL_BYTES:
        raise ProjectPolicyError("Approved project exceeds byte budget")
    tests = _test_files(checked)
    if not tests:
        return {"outcome": "no_tests", "passed": False, "tests_run": 0,
                "log": "No test_*.py files in approved artifact", "executed": False}
    if len(tests) > MAX_TEST_FILES:
        raise ProjectPolicyError("Too many test files")
    # Verify isolation before copying/untrusted code execution.
    preflight(secure)
    with tempfile.TemporaryDirectory(dir=secure, prefix=".mio-sandbox-") as scratch:
        staging = Path(scratch)
        os.chmod(staging, 0o700)
        for file in checked["files"]:
            dest = staging.joinpath(*file["path"].split("/"))
            dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            # Copy exact approved bytes from DB, not arbitrary workspace filesystem entries.
            fd = os.open(dest, os.O_WRONLY | os.O_EXCL | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as target:
                target.write(file["content"].encode("utf-8"))
        rc, log, timed_out, overflow = _bounded_run(sandbox_argv(staging, HARNESS))
    match = re.findall(r"MIO_VERIFIER_TESTS_RUN=(\d+)", log)
    count = int(match[-1]) if match else 0
    passed = rc == 0 and count > 0 and not timed_out and not overflow
    outcome = (
        "timeout" if timed_out else "output_limit" if overflow else
        "passed" if passed else "failed"
    )
    return {"outcome": outcome, "passed": passed, "tests_run": count,
            "return_code": rc, "log": log[:OUTPUT_LIMIT], "executed": True,
            "isolation": "bwrap user/pid/net/ipc/uts; read-only filesystem; no GPUs"}
