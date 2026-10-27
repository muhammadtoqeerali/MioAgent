"""SCORPIO9D3B5: pinned private Playwright, offline DOM rendering of public evidence.

Network retrieval is deliberately separate: mio.web_evidence validates and fetches
one public HTTPS URL. The browser only receives escaped text via a data: URI and
runs with all network namespaces unshared. This is NOT a general browser or a
permission-grant mechanism. No model-facing execution hook is installed here.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
from pathlib import Path

from mio.web_evidence import fetch_public_page

VERSION = "SCORPIO9D3B5"
ROOT = Path(f"/var/tmp/mioagent-native-{os.getuid()}/scorpio9d3b4-playwright-1_64_1")
BINARY = ROOT / "browsers/chromium_headless_shell-1248/chrome-headless-shell-linux64/chrome-headless-shell"
BINARY_SHA256 = "4fa61f0ba0b4f89b7bec242c32ca16d3bccf69dbfef0651924a9ba8fede5f9d6"
VENV_PYTHON = ROOT / "venv/bin/python"
PUBLIC_DEMO_URL = "https://www.python.org/"
MAX_EXCERPT_BYTES = 8000


class BrowserDenied(RuntimeError):
    """Deny unverified browser paths, mounts, or execution evidence."""


def _no_symlink_ancestors(path: Path) -> None:
    if not path.is_absolute():
        raise BrowserDenied("Non-absolute browser resource")
    for item in (path, *path.parents):
        if item == Path("/"):
            break
        if item.is_symlink():
            raise BrowserDenied("Browser resource traverses a symlink")


def attest_browser() -> dict[str, str]:
    """Match the exact binary proven by SCORPIO9D3B4R2, not an arbitrary browser."""
    if os.geteuid() == 0 or platform.system() != "Linux" or platform.machine() not in {"x86_64", "AMD64"}:
        raise BrowserDenied("Requires unprivileged Linux x86-64")
    _no_symlink_ancestors(ROOT)
    _no_symlink_ancestors(BINARY)
    for folder in (ROOT.parent, ROOT, ROOT / "browsers", ROOT / "venv"):
        try:
            metadata = folder.lstat()
        except OSError as exc:
            raise BrowserDenied("Private browser directory missing") from exc
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise BrowserDenied("Private browser directory owner/type mismatch")
        if folder in (ROOT.parent, ROOT) and stat.S_IMODE(metadata.st_mode) & 0o077:
            raise BrowserDenied("Browser private storage outer boundary exposed")
    try:
        info = BINARY.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or not info.st_mode & stat.S_IXUSR or info.st_mode & 0o022
                or info.st_nlink != 1 or not 10_000_000 <= info.st_size <= 600_000_000):
            raise BrowserDenied("Browser executable unsafe ownership or permissions")
        with BINARY.open("rb") as handle:
            if handle.read(4) != b"\x7fELF":
                raise BrowserDenied("Browser executable not ELF")
        with BINARY.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if digest != BINARY_SHA256:
            raise BrowserDenied("Browser executable hash changed")
        if not VENV_PYTHON.is_file():
            raise BrowserDenied("Pinned private Playwright environment missing")
        interpreter = VENV_PYTHON.resolve(strict=True)
        if not interpreter.is_relative_to(ROOT / "venv"):
            raise BrowserDenied("Playwright interpreter escaped private venv")
    except OSError as exc:
        raise BrowserDenied("Browser attestation unavailable") from exc
    return {"browser_sha256": digest, "private_root": str(ROOT)}


def _sandbox() -> list[str]:
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise BrowserDenied("Bubblewrap unavailable")
    command = [bwrap, "--unshare-all", "--new-session", "--die-with-parent",
               "--ro-bind", "/usr", "/usr", "--proc", "/proc", "--dev", "/dev",
               "--tmpfs", "/tmp", "--dir", "/etc", "--dir", "/run", "--dir", "/var",
               "--dir", "/var/tmp", "--dir", str(ROOT.parent),
               "--ro-bind", str(ROOT), str(ROOT)]
    for name in ("/lib", "/lib64", "/bin", "/sbin"):
        path = Path(name)
        if path.is_symlink():
            target = os.readlink(path)
            if not target.startswith(("usr/", "/usr/")):
                raise BrowserDenied("Unexpected system link layout")
            command.extend(["--symlink", target, name])
        elif path.is_dir():
            command.extend(["--ro-bind", name, name])
    for name in ("/etc/fonts", "/etc/ld.so.cache", "/etc/localtime", "/etc/nsswitch.conf"):
        if Path(name).exists():
            command.extend(["--ro-bind", name, name])
    return command


def _runtime_prefix() -> Path:
    code = ("import json,sys,sysconfig,encodings;"
            "print(json.dumps({'prefix':sys.base_prefix,"
            "'stdlib':sysconfig.get_path('stdlib'),'encoding':encodings.__file__}))")
    proc = subprocess.run(
        [str(VENV_PYTHON), "-B", "-c", code], cwd=ROOT,
        env={"HOME": "/tmp", "PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=15, check=False,
    )
    if proc.returncode != 0:
        raise BrowserDenied("Pinned Python runtime introspection failed")
    try:
        result = json.loads(proc.stdout)
        prefix = Path(result["prefix"])
        stdlib = Path(result["stdlib"])
        encoding = Path(result["encoding"])
    except (ValueError, KeyError, TypeError) as exc:
        raise BrowserDenied("Unrecognized Python runtime prefix") from exc
    if (not prefix.is_absolute() or len(prefix.parts) < 3
            or not prefix.is_dir() or not stdlib.is_relative_to(prefix)
            or not encoding.is_relative_to(stdlib) or not encoding.is_file()):
        raise BrowserDenied("Unsafe Python runtime prefix")
    _no_symlink_ancestors(prefix)
    return prefix


def _mount_python(command: list[str], prefix: Path) -> list[str]:
    if prefix.is_relative_to(Path("/usr")) or prefix.is_relative_to(ROOT):
        return command
    if prefix in {Path("/home"), Path("/mnt"), Path("/opt"), Path("/var"), Path("/tmp")}:
        raise BrowserDenied("Python runtime prefix too broad")
    for parent in reversed(prefix.parents):
        if (parent == Path("/") or parent.is_relative_to(Path("/usr"))
                or parent in {Path("/var"), Path("/var/tmp"), ROOT.parent}
                or parent.is_relative_to(ROOT)):
            continue
        command.extend(["--dir", str(parent)])
    command.extend(["--ro-bind", str(prefix), str(prefix)])
    return command


# This Python source runs *only inside Bubblewrap*. Untrusted documentation text
# is base64 data, HTML-escaped before rendering; it cannot supply Python or JS.
_SANDBOX_CODE = r'''
import base64
import hashlib
import html
import json
import sys
from urllib.parse import quote
from playwright.sync_api import sync_playwright

value = base64.b64decode(sys.argv[1], validate=True).decode("utf-8")
page_html = ('<!doctype html><html><meta charset="utf-8"><body>'
             '<pre id="scorpio-evidence">' + html.escape(value) + '</pre>'
             '<div id="scorpio-proof">pending</div>'
             '<script>document.getElementById("scorpio-proof").textContent="JS_OK_9D3B5";</script>'
             '</body></html>')
with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, args=[
        "--no-sandbox", "--disable-dev-shm-usage", "--disable-background-networking",
        "--disable-component-update", "--disable-extensions"])
    context = browser.new_context(accept_downloads=False, service_workers="block")
    page = context.new_page()
    page.goto("data:text/html;charset=utf-8," + quote(page_html, safe=""),
              wait_until="load", timeout=15000)
    rendered = page.locator("#scorpio-evidence").inner_text(timeout=8000)
    proof = page.locator("#scorpio-proof").inner_text(timeout=8000)
    context.close()
    browser.close()
if proof != "JS_OK_9D3B5" or rendered != value:
    raise RuntimeError("Isolated browser did not faithfully render documentation")
print(json.dumps({"verified": True,
                  "rendered_sha256": hashlib.sha256(rendered.encode()).hexdigest(),
                  "javascript_executed": True, "network": "disabled"}))
'''


def render_offline_excerpt(excerpt: str) -> dict:
    """Render inert evidence; fail closed if browser output is not independently verified."""
    if not isinstance(excerpt, str) or not excerpt.strip() or len(excerpt.encode("utf-8")) > MAX_EXCERPT_BYTES:
        raise BrowserDenied("Invalid or oversized public-document excerpt")
    attestation = attest_browser()
    prefix = _runtime_prefix()
    command = _mount_python(_sandbox(), prefix)
    command.extend(["--clearenv", "--setenv", "HOME", "/tmp", "--setenv", "TMPDIR", "/tmp",
                    "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "LANG", "C.UTF-8",
                    "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
                    "--setenv", "PLAYWRIGHT_BROWSERS_PATH", str(ROOT / "browsers"),
                    "--", str(VENV_PYTHON), "-B", "-c", _SANDBOX_CODE,
                    base64.b64encode(excerpt.encode()).decode("ascii")])
    try:
        run = subprocess.run(command, cwd=ROOT, env={"HOME": "/tmp", "PATH": "/usr/bin:/bin"},
                             capture_output=True, text=True, timeout=85, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BrowserDenied("Offline browser execution unavailable") from exc
    if run.returncode != 0 or len(run.stdout) > 1800:
        raise BrowserDenied("Offline browser exited without trusted rendering proof")
    try:
        result = json.loads(run.stdout.strip())
    except (ValueError, TypeError) as exc:
        raise BrowserDenied("Browser proof is not strict JSON") from exc
    if (result != {"verified": True,
                   "rendered_sha256": hashlib.sha256(excerpt.encode()).hexdigest(),
                   "javascript_executed": True, "network": "disabled"}):
        raise BrowserDenied("Browser proof did not match original excerpt")
    return {**result, **attestation}


def render_approved_demo(url: str, *, owner_approved: bool = False) -> dict:
    """One predetermined public page only. The CLI owns the approval gate.

    This is NOT an agent-callable public URL grant: workers must later obtain
    scope from an authenticated owner-approved broker before any arbitrary URL.
    """
    if owner_approved is not True or url != PUBLIC_DEMO_URL:
        raise BrowserDenied("One exact public demo URL and owner approval required")
    evidence = fetch_public_page(url)
    if evidence.get("page_verified") is not True:
        raise BrowserDenied("Public HTTPS content unverified")
    render = render_offline_excerpt(evidence["page_excerpt"])
    return {"phase": VERSION, "public_url": url, "page_sha256": evidence["page_sha256"],
            "page_encoding": evidence.get("page_encoding", "identity"),
            "excerpt_chars": len(evidence["page_excerpt"]), **render,
            "downloads": False, "installs": False, "browser_network_enabled": False,
            "production_files_modified": False}
