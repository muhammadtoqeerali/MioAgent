"""Owner-granted, expiring, scope-limited agent tool permissions.

The AI cannot issue grants through this module. Owner grant issuance is a local
interactive terminal operation, never an API request or an autonomous tool.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import sys
import time
from pathlib import Path

from mio import agent_vault

CAPABILITIES = frozenset({"repo.read", "workspace.write", "tests.run", "browser.local.read"})
SCOPE = re.compile(r"[a-zA-Z0-9_-]{1,40}\Z")
TOKEN = re.compile(r"[a-f0-9]{32}\Z")
MAX_HOURS = 168


class PermissionDenied(PermissionError):
    pass


def _grants() -> Path:
    root = agent_vault.VAULT / "agents" / "grants"
    agent_vault._directory(root)
    return root


def grant_interactively(session: str, caps: list[str], hours: int) -> str:
    """Local owner CLI operation; never invoke automatically from an agent."""
    if not sys.stdin.isatty() or not sys.stdout.isatty() or os.geteuid() == 0:
        raise PermissionDenied("Owner must authorize using an interactive terminal")
    if not SCOPE.fullmatch(session) or not caps or set(caps) - CAPABILITIES:
        raise PermissionDenied("Invalid session or capability")
    if not 1 <= hours <= MAX_HOURS:
        raise PermissionDenied("Grant duration is limited to seven days")
    if not agent_vault.project_storage_status()["live_cutover_supported"]:
        raise PermissionDenied("Portable provisional vault cannot issue persistent tool grants")
    agent_vault.prepare()
    code = secrets.token_hex(4)
    print("Owner approval: session=", session, " capabilities=", sorted(set(caps)),
          " expires_in_hours=", hours, sep="")
    print("No terminal shell, deletion, arbitrary browser site, remote laptop or publishing granted.")
    typed = input("Type APPROVE " + code + " to authorize: ").strip()
    if typed != "APPROVE " + code:
        raise PermissionDenied("Owner did not approve")
    grant_id = secrets.token_hex(16)
    record = {"format": 1, "grant": grant_id, "session": session,
              "capabilities": sorted(set(caps)), "uid": os.getuid(),
              "issued": int(time.time()), "expires": int(time.time()) + hours * 3600}
    agent_vault._write_new(_grants() / (grant_id + ".json"),
                           json.dumps(record, sort_keys=True).encode())
    return grant_id


def require(grant_id: str, session: str, capability: str) -> dict:
    """Read one exact grant; never expand authority based on model output."""
    if not TOKEN.fullmatch(grant_id) or not SCOPE.fullmatch(session) or capability not in CAPABILITIES:
        raise PermissionDenied("Invalid permission request")
    if not agent_vault.project_storage_status()["live_cutover_supported"]:
        raise PermissionDenied("Persistent tool grants disabled on provisional storage")
    path = _grants() / (grant_id + ".json")
    try:
        agent_vault._file(path, max_bytes=4096)
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, agent_vault.VaultError) as exc:
        raise PermissionDenied("Grant unavailable") from exc
    if (record.get("format") != 1 or record.get("grant") != grant_id or
            record.get("session") != session or record.get("uid") != os.getuid() or
            capability not in record.get("capabilities", []) or
            not isinstance(record.get("expires"), int) or
            time.time() >= record["expires"]):
        raise PermissionDenied("Grant expired, revoked or out of scope")
    return record


def revoke_interactively(grant_id: str) -> None:
    if not sys.stdin.isatty() or os.geteuid() == 0 or not TOKEN.fullmatch(grant_id):
        raise PermissionDenied("Local owner terminal required to revoke")
    if not agent_vault.project_storage_status()["live_cutover_supported"]:
        raise PermissionDenied("Persistent grants unavailable on provisional storage")
    path = _grants() / (grant_id + ".json")
    if not path.exists():
        return
    agent_vault._file(path, max_bytes=4096)
    typed = input("Type REVOKE to disable grant " + grant_id[:8] + ": ").strip()
    if typed != "REVOKE":
        raise PermissionDenied("Revocation not confirmed")
    # Deletion is limited to the exact owner-only grant, never user files.
    path.unlink()
