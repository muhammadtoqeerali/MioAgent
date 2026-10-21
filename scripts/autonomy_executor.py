"""AUT3B owner CLI: preview or sandbox-test a registered repo goal for a supervisor step.

Example:
  python -m scripts.autonomy_executor preview JOB --step 0 --goal-id DIGEST --plan-sha256 DIGEST
  python -m scripts.autonomy_executor execute JOB --step 0 --goal-id DIGEST --plan-sha256 DIGEST --owner-approve
This CLI intentionally has no --apply, --commit or --push option.
"""

from __future__ import annotations

import argparse
import asyncio
import json

from mio.autonomy_executor import inspect_binding, run_approved_step
from mio.autonomy_program import path_for


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "execute"))
    parser.add_argument("job")
    parser.add_argument("--step", type=int, required=True)
    parser.add_argument("--goal-id", required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--owner-approve", action="store_true")
    args = parser.parse_args()
    store = path_for()
    try:
        if args.action == "preview":
            if args.owner_approve:
                parser.error("Preview does not accept execution approval")
            data = inspect_binding(store, args.job, args.step, args.goal_id, args.plan_sha256)
            print(json.dumps(data, indent=2))
            print("READ ONLY: no code was generated, applied, or published")
        else:
            data = asyncio.run(run_approved_step(
                store, args.job, args.step, args.goal_id, args.plan_sha256,
                owner_confirmed=args.owner_approve,
            ))
            print(json.dumps(data, indent=2))
            print("Sandbox-tested proposal only. Inspect patch and review before separately applying.")
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        parser.exit(1, f"STOP: {type(exc).__name__}: {str(exc)[:240]}\n")


if __name__ == "__main__":
    main()
