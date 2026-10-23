"""Bounded deterministic agent tools, not a free-form shell or laptop connector.

All file mutations go to per-session workspaces under the MioAgent project.
Paths in prompts and model output never escape the explicit allowed roots.
"""
from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path
from urllib.request import Request, urlopen

from mio import agent_permissions, agent_vault

MAX_READ = 1_000_000
MAX_WRITE = 2_000_000
MAX_LIST = 200
SAFE_PATH = re.compile(r"[A-Za-z0-9._/-]{1,240}\Z")


class ToolDenied(PermissionError):
    pass


def _private_path(relative: str) -> bool:
    parts = _relative(relative).parts
    blocked = {".git", ".mioagent-private", "node_modules", ".next", ".env",
               "secrets", "private", "credentials", "models"}
    return any(p in blocked or p.startswith(".env") or
               p.endswith((".pem", ".key", ".p12")) for p in parts)


def _relative(relative: str) -> Path:
    if (not isinstance(relative, str) or not SAFE_PATH.fullmatch(relative)
            or relative.startswith("/") or "\\" in relative):
        raise ToolDenied("Invalid relative path")
    path = Path(relative)
    if any(p in ("", ".", "..") for p in path.parts):
        raise ToolDenied("Path traversal denied")
    return path


def _resolve_safe(root: Path, relative: str) -> Path:
    agent_vault._directory(root, private=False)
    item = root
    for part in _relative(relative).parts:
        item = item / part
        if item.is_symlink():
            raise ToolDenied("Symlink access denied")
    if not item.is_relative_to(root):
        raise ToolDenied("Outside authorized root")
    return item


def _workspace(session: str) -> Path:
    if not agent_permissions.SCOPE.fullmatch(session):
        raise ToolDenied("Invalid session")
    root = agent_vault.VAULT / "agents" / "workspaces"
    agent_vault._directory(root)
    folder = root / session
    if not folder.exists() and not folder.is_symlink():
        folder.mkdir(mode=0o700)
    agent_vault._directory(folder)
    return folder


def read_repo_text(grant: str, session: str, relative: str) -> str:
    agent_permissions.require(grant, session, "repo.read")
    p = _resolve_safe(agent_vault.PROJECT, relative)
    # Avoid granting access to private data, VCS internals and generated dependencies.
    if _private_path(relative):
        raise ToolDenied("Private or generated project path denied")
    try:
        info = p.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_READ:
            raise ToolDenied("Unsupported file type or size")
        return p.read_text(encoding="utf-8")
    except (UnicodeError, OSError) as exc:
        raise ToolDenied("File not readable") from exc


def list_repo(grant: str, session: str, relative: str = "mio") -> list[str]:
    agent_permissions.require(grant, session, "repo.read")
    if _private_path(relative):
        raise ToolDenied("Private project path denied")
    folder = _resolve_safe(agent_vault.PROJECT, relative)
    if not folder.is_dir():
        raise ToolDenied("Folder unavailable")
    entries = sorted(folder.iterdir(), key=lambda p: p.name)
    if len(entries) > MAX_LIST:
        raise ToolDenied("Listing exceeds limit")
    return [x.name + ("/" if x.is_dir() and not x.is_symlink() else "")
            for x in entries if not x.is_symlink() and not x.name.startswith(".env")]


def write_workspace(grant: str, session: str, relative: str, content: str) -> Path:
    agent_permissions.require(grant, session, "workspace.write")
    if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_WRITE:
        raise ToolDenied("Workspace content exceeds limit")
    root = _workspace(session)
    path = _resolve_safe(root, relative)
    # First version allows only new files, not overwrites or deletions.
    if not path.parent.is_dir() or path.exists() or path.is_symlink():
        raise ToolDenied("Only new files inside existing workspace folders are allowed")
    agent_vault._directory(path.parent)
    agent_vault._write_new(path, content.encode("utf-8"))
    return path


def run_approved_tests(grant: str, session: str, test_file: str) -> dict:
    agent_permissions.require(grant, session, "tests.run")
    if not re.fullmatch(r"tests/test_[a-z0-9_]+\.py", test_file):
        raise ToolDenied("Test execution requires an explicit repository test file")
    path = _resolve_safe(agent_vault.PROJECT, test_file)
    if not path.is_file() or path.is_symlink():
        raise ToolDenied("Test file unavailable")
    py = Path.home() / ".cache/mioagent/phase1-venv/bin/python"
    if not py.is_file():
        raise ToolDenied("Existing tested Python environment unavailable")
    # Place command scratch files inside the owner-selected MioAgent project.
    workspace = _workspace(session)
    scratch = workspace / 'test-tmp'
    if not scratch.exists() and not scratch.is_symlink():
        scratch.mkdir(mode=0o700)
    agent_vault._directory(scratch)
    # This is a deliberately bounded pytest invocation, not an arbitrary terminal.
    result = subprocess.run([str(py), "-m", "pytest", "-q", test_file,
                             "-p", "no:cacheprovider"],
                            cwd=agent_vault.PROJECT, capture_output=True, text=True,
                            timeout=120, check=False, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "TMPDIR": str(scratch),
                                                    "TMP": str(scratch), "TEMP": str(scratch)})
    return {"exit": result.returncode, "stdout_tail": result.stdout[-6000:],
            "stderr_tail": result.stderr[-1000:]}


def read_local_dashboard(grant: str, session: str, page: str = "/health") -> dict:
    agent_permissions.require(grant, session, "browser.local.read")
    if page not in ("/health",):
        raise ToolDenied("Only approved read-only local pages supported")
    base = "http://127.0.0.1:8000"
    try:
        with urlopen(Request(base + page, method="GET"), timeout=4) as response:
            return {"status": response.status, "body": response.read(2048).decode("utf-8", errors="replace")}
    except OSError as exc:
        raise ToolDenied("Local API unavailable") from exc
