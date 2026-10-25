"""Manual owner-only CLI for a disabled-by-default, sandboxed file digest tool."""
import argparse
import json

from mio.scorpio9c_tools import grant, input_directory, inspect, registry, revoke
from mio.work_core import RUNTIME, WorkStop


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("registry")
    folder = commands.add_parser("input-folder")
    folder.add_argument("--project", required=True)
    approval = commands.add_parser("grant")
    approval.add_argument("--project", required=True)
    approval.add_argument("--plan", required=True)
    approval.add_argument("--file", required=True)
    approval.add_argument("--minutes", type=int, default=10)
    inspection = commands.add_parser("inspect")
    inspection.add_argument("--grant", required=True)
    inspection.add_argument("--file", required=True)
    revocation = commands.add_parser("revoke")
    revocation.add_argument("--grant", required=True)
    args = parser.parse_args()
    root = RUNTIME / "work"
    try:
        if args.action == "registry":
            value = registry()
        elif args.action == "input-folder":
            value = {"input_folder": str(input_directory(root, args.project))}
        elif args.action == "grant":
            value = grant(root, args.project, args.plan, args.file, minutes=args.minutes)
        elif args.action == "inspect":
            value = inspect(root, args.grant, args.file)
        else:
            revoke(root, args.grant)
            value = {"revoked": True}
        print(json.dumps(value, indent=2))
    except (WorkStop, OSError, ValueError) as exc:
        parser.exit(2, f"DENIED: {type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    main()
