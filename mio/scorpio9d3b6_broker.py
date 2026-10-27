"""SCORPIO9D3B6: single-use scope-bound public-evidence browser grants.

This is a primitive for a future authenticated Work API; NOT an owner-auth API
or a general model-callable browser. The demonstration's CLI is the sole
issuer currently installed. Browser execution remains network-disabled.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import sqlite3
import stat
import time
from contextlib import contextmanager
from pathlib import Path

from mio.scorpio9d3b5_browser import BrowserDenied, render_offline_excerpt
from mio.web_evidence import EvidenceError, fetch_public_page, public_target

ID = re.compile(r"[0-9a-f]{32}\Z")
MAX_TTL = 300
MAX_URL_BYTES = 1500


class ScopeDenied(ValueError):
    """Browser scope is missing, expired, consumed, or otherwise invalid."""


def _id(value: str) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ScopeDenied("Invalid project or run binding")
    return value


def _directory(root: Path) -> Path:
    root = Path(root)
    if (not root.is_absolute() or root.is_symlink()
            or root.parent.is_symlink() or not root.parent.is_dir()):
        raise ScopeDenied("Private broker directory must be under an existing directory")
    parent = root.parent.lstat()
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid()
            or stat.S_IMODE(parent.st_mode) & 0o077):
        raise ScopeDenied("Broker parent directory is not owner-private")
    if not root.exists():
        root.mkdir(mode=0o700)
    info = root.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise ScopeDenied("Broker directory is not owner-private")
    return root


@contextmanager
def _store(root: Path):
    path = _directory(root) / "browser-grants.sqlite3"
    if path.is_symlink():
        raise ScopeDenied("Broker ledger symlink refused")
    if path.exists():
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077 or info.st_nlink != 1):
            raise ScopeDenied("Broker ledger ownership or permissions invalid")
    else:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
    conn = sqlite3.connect(path, timeout=8)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=8000")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS grants(
          token_hash TEXT PRIMARY KEY, project TEXT NOT NULL, run TEXT NOT NULL,
          url TEXT NOT NULL, issued INTEGER NOT NULL, expires INTEGER NOT NULL,
          used INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'approved',
          page_hash TEXT, result_hash TEXT)
    """)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _url(value: str) -> str:
    if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_URL_BYTES:
        raise ScopeDenied("URL exceeds scope limit")
    try:
        public_target(value)
    except EvidenceError as exc:
        raise ScopeDenied("Only safely validated public HTTPS URLs are allowed") from exc
    return value


def issue_one_use(root: Path, *, project: str, run: str, url: str,
                  owner_approved: bool, ttl: int = 180) -> str:
    """Create a capability after a separate trusted caller authenticated its owner.

    The boolean is a secondary guard, NOT an authentication mechanism. Model
    text must never reach this function as code, nor choose its owner_approved.
    """
    if owner_approved is not True:
        raise ScopeDenied("Explicit verified owner approval required")
    project, run, url = _id(project), _id(run), _url(url)
    if type(ttl) is not int or not 1 <= ttl <= MAX_TTL:
        raise ScopeDenied("Approval lifetime exceeds five minutes")
    issued = int(time.time())
    token = secrets.token_hex(32)
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    with _store(root) as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM grants WHERE run=?", (run,)).fetchone():
            raise ScopeDenied("Run binding already has an issued browser grant")
        conn.execute("INSERT INTO grants(token_hash,project,run,url,issued,expires) "
                     "VALUES (?,?,?,?,?,?)",
                     (token_hash, project, run, url, issued, issued + ttl))
    return token


def claim_once(root: Path, *, project: str, run: str, url: str, token: str) -> str:
    """Atomically consume a grant BEFORE network I/O; interrupted runs need new review."""
    project, run, url = _id(project), _id(run), _url(url)
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{64}", token):
        raise ScopeDenied("Malformed scope token")
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    current = int(time.time())
    with _store(root) as conn:
        conn.execute("BEGIN IMMEDIATE")
        changed = conn.execute(
            "UPDATE grants SET used=1,state='claimed' WHERE token_hash=? "
            "AND project=? AND run=? AND url=? AND used=0 AND expires>?",
            (token_hash, project, run, url, current),
        )
        if changed.rowcount != 1:
            raise ScopeDenied("Browser scope unavailable, consumed, or expired")
    return token_hash


def _finish(root: Path, token_hash: str, *, success: bool,
            page_hash: str | None = None, render_hash: str | None = None) -> None:
    with _store(root) as conn:
        conn.execute("BEGIN IMMEDIATE")
        changed = conn.execute(
            "UPDATE grants SET state=?,page_hash=?,result_hash=? "
            "WHERE token_hash=? AND used=1 AND state='claimed'",
            ("verified" if success else "failed", page_hash, render_hash, token_hash),
        )
        if changed.rowcount != 1:
            raise ScopeDenied("Browser claim ledger changed unexpectedly")


def execute_granted(root: Path, *, project: str, run: str, url: str, token: str) -> dict:
    """Fetch one approved public page and render inert evidence in offline browser."""
    scope = claim_once(root, project=project, run=run, url=url, token=token)
    try:
        evidence = fetch_public_page(url)
        if evidence.get("page_verified") is not True or not evidence.get("page_excerpt"):
            raise ScopeDenied("Public page has no verified evidence")
        rendering = render_offline_excerpt(evidence["page_excerpt"])
        if (rendering.get("verified") is not True
                or rendering.get("javascript_executed") is not True
                or rendering.get("network") != "disabled"):
            raise ScopeDenied("Offline browser proof missing")
        _finish(root, scope, success=True, page_hash=evidence["page_sha256"],
                render_hash=rendering["rendered_sha256"])
        return {"state": "verified", "project": project, "run": run,
                "url": url, "scope_sha256": scope,
                "page_sha256": evidence["page_sha256"],
                "rendered_sha256": rendering["rendered_sha256"],
                "javascript_executed": True, "browser_network": "disabled",
                "downloads": False, "installs": False, "source_changes": False}
    except (ScopeDenied, EvidenceError, BrowserDenied, OSError, ValueError, RuntimeError):
        _finish(root, scope, success=False)
        raise
