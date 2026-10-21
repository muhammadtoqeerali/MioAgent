"""Owner-invoked AUT4A engineering benchmarks. No source patch application."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
from pathlib import Path

from mio.autonomy_benchmarks import CASE_IDS, create_campaign, run_case, status_campaign
from mio.autonomy_program import path_for


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--base-commit", required=True)
    run = sub.add_parser("run")
    run.add_argument("campaign")
    run.add_argument("--case", choices=CASE_IDS, required=True)
    run.add_argument("--owner-run-model", action="store_true", required=True)
    stat = sub.add_parser("status")
    stat.add_argument("campaign")
    args = parser.parse_args()
    try:
        store = path_for()
        if args.action == "prepare":
            base = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                           cwd=Path(__file__).resolve().parents[1], text=True).strip()
            if base != args.base_commit:
                raise RuntimeError("Git baseline changed, refuse benchmark preparation")
            record = create_campaign(store, base)
            print(json.dumps({"campaign": record["id"], "cases": list(CASE_IDS),
                              "base_commit": base, "model_calls": False}, indent=2))
        elif args.action == "status":
            print(json.dumps(status_campaign(store, args.campaign), indent=2))
        else:
            if not args.owner_run_model:
                raise ValueError("Explicit owner model-execution flag required")
            result = asyncio.run(run_case(store, args.campaign, args.case))
            print(json.dumps(result, indent=2))
            if result["state"] != "passed":
                parser.exit(1, "STOP: Benchmark case did not pass independent tests\n")
    except (RuntimeError, ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"STOP: {type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    main()
