"""Owner-invoked post-repair hidden-test audits of existing AUT4A campaigns."""

from __future__ import annotations

import argparse
import json

from mio.autonomy_benchmarks import CASE_IDS
from mio.autonomy_holdouts import holdout_status, verify_holdout
from mio.autonomy_program import path_for


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="action", required=True)
    check = subs.add_parser("run")
    check.add_argument("campaign")
    check.add_argument("--case", choices=CASE_IDS, required=True)
    check.add_argument("--owner-run-sandbox", action="store_true", required=True)
    status = subs.add_parser("status")
    status.add_argument("campaign")
    args = parser.parse_args()
    try:
        store = path_for()
        if args.action == "status":
            value = holdout_status(store, args.campaign)
        else:
            if not args.owner_run_sandbox:
                raise ValueError("Owner must explicitly opt in to sandbox verification")
            value = verify_holdout(store, args.campaign, args.case)
        print(json.dumps(value, indent=2))
        if args.action == "run" and value["state"] != "passed":
            parser.exit(1, "STOP: Candidate failed at least one independent holdout test\n")
    except (RuntimeError, ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(1, f"STOP: {type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    main()
