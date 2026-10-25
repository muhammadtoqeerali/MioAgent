"""Owner-terminal-only Scorpio9C3 staged step grant and policy-preview CLI."""
from __future__ import annotations

import argparse
import json

from mio.scorpio9c3_step_grants import bindings, check_queued_step, stage
from mio.work_core import RUNTIME, WorkStop


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    stage_cmd = sub.add_parser("stage")
    stage_cmd.add_argument("--project", required=True)
    stage_cmd.add_argument("--plan", required=True)
    stage_cmd.add_argument("--step", required=True)
    stage_cmd.add_argument("--file", required=True)
    stage_cmd.add_argument("--minutes", type=int, default=15)
    inventory = sub.add_parser("bindings")
    inventory.add_argument("--project")
    preview = sub.add_parser("check-queued")
    preview.add_argument("--run", required=True)
    args = parser.parse_args()
    root = RUNTIME / "work"
    try:
        if args.action == "stage":
            result = stage(root, args.project, args.plan, args.step, args.file, minutes=args.minutes)
        elif args.action == "bindings":
            result = bindings(root, project_id=args.project)
        else:
            result = check_queued_step(root, args.run)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, WorkStop) as exc:
        parser.exit(2, f"DENIED: {type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    main()
