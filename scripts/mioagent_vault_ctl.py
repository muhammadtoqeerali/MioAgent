#!/usr/bin/env python3
"""Owner-only MioAgent project vault utility; no writes outside project.

Commands: status, grant (interactive), revoke (interactive).
Data checkpoint is exclusively managed by the guarded release installer, which
checks idle queues before copying from the existing native runtime.
"""
from __future__ import annotations

import argparse
import json
import os

from mio import agent_permissions, agent_vault


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="mode", required=True)
    actions.add_parser("status")
    grant = actions.add_parser("grant")
    grant.add_argument("--session", required=True)
    grant.add_argument("--hours", type=int, default=8)
    grant.add_argument("--capability", action="append", required=True,
                       choices=sorted(agent_permissions.CAPABILITIES))
    revoke = actions.add_parser("revoke")
    revoke.add_argument("--grant", required=True)
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise SystemExit("Refusing root")
    if args.mode == "status":
        folder = agent_vault.VAULT
        if folder.exists() or folder.is_symlink():
            agent_vault._directory(folder)
            details = agent_vault.project_storage_status()
            print(json.dumps({"vault": str(folder), "owner_private": details["native_private_mode"],
                              "storage": details, "active_chat_db_migrated": False,
                              "active_work_db_migrated": False,
                              "agent_permissions_available": details["live_cutover_supported"]},
                             sort_keys=True))
        else:
            print("Vault not prepared; run the guarded VAULT5A installer first")
    elif args.mode == "grant":
        identifier = agent_permissions.grant_interactively(args.session, args.capability, args.hours)
        print("OWNER GRANT CREATED:", identifier)
        print("Grant is not connected to autonomous Work execution yet.")
    elif args.mode == "revoke":
        agent_permissions.revoke_interactively(args.grant)
        print("Owner grant revoked if present")


if __name__ == "__main__":
    main()
