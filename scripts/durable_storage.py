"""Operator-only backups. This tool does not change the active MioAgent runtime."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mio.durable_storage import (
    StorageError,
    create_snapshot,
    initialize_target,
    inventory,
    verify_snapshot,
)
from scripts.native_runtime import RUNTIME, is_running


def assert_stopped() -> None:
    if is_running("api") or is_running("dashboard"):
        raise StorageError("Stop MioAgent API and dashboard before snapshot; no online artifact copy")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("audit")
    init = sub.add_parser("init")
    init.add_argument("--destination", required=True, type=Path)
    snap = sub.add_parser("snapshot")
    snap.add_argument("--destination", required=True, type=Path)
    snap.add_argument("--max-mib", type=int, default=2048)
    verify = sub.add_parser("verify")
    verify.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "audit":
            result = inventory(RUNTIME)
        elif args.action == "init":
            result = {"private_target": str(initialize_target(args.destination))}
        elif args.action == "snapshot":
            assert_stopped()
            path = create_snapshot(RUNTIME, args.destination, max_mib=args.max_mib)
            result = {"snapshot": str(path), **verify_snapshot(path)}
        else:
            result = verify_snapshot(args.snapshot)
    except (StorageError, OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(1, f"STOP: {exc}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
