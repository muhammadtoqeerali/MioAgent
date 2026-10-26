"""Owner CLI for opt-in SCORPIO9C6 synthetic native Work canary."""

from __future__ import annotations

import argparse
import json

from mio.scorpio9c6_live_canary import APPROVAL, prepare_canary, readiness, verify_canary
from mio.work_core import WorkStop


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("readiness")
    create = commands.add_parser("prepare")
    create.add_argument("--approval", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--project", required=True)
    verify.add_argument("--plan", required=True)
    args = parser.parse_args()
    try:
        if args.action == "readiness":
            result = readiness()
        elif args.action == "prepare":
            if args.approval != APPROVAL:
                raise WorkStop("Explicit production canary consent not provided")
            result = prepare_canary()
        else:
            result = verify_canary(args.project, args.plan)
        print(json.dumps(result, indent=2, sort_keys=True))
    except (WorkStop, OSError, ValueError) as exc:
        # Never print raw paths/secrets from unexpected OS failures.
        parser.exit(2, f"DENIED: {type(exc).__name__}: {str(exc) if isinstance(exc, WorkStop) else 'operation unavailable'}\n")


if __name__ == "__main__":
    main()
