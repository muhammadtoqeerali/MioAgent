"""Owner CLI for AUT3A supervisor jobs and backlog milestone verification.

No model inference, shell execution, repository changes or service restarts.
"""

from __future__ import annotations

import argparse
import json

from mio.autonomy_program import path_for, read_program, ready_tasks, verify_task
from mio.autonomy_supervisor import (
    approve_job,
    begin_step,
    complete_step,
    create_job,
    finalize_job,
    read_jobs,
    reconcile_interrupted,
    resume_job,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("status")
    sub.add_parser("reconcile")
    create = sub.add_parser("create")
    create.add_argument("task")
    approve = sub.add_parser("approve")
    approve.add_argument("job")
    approve.add_argument("--plan-sha256", required=True)
    approve.add_argument("--owner-approve", action="store_true", required=True)
    for command in ("begin", "finish"):
        p = sub.add_parser(command)
        p.add_argument("job")
        p.add_argument("index", type=int)
        if command == "finish":
            p.add_argument("--evidence-sha256", required=True)
    for command in ("resume", "finalize"):
        p = sub.add_parser(command)
        p.add_argument("job")
        p.add_argument("--owner-approve", action="store_true", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("task")
    verify.add_argument("--evidence-sha256", required=True)
    verify.add_argument("--summary", required=True)
    verify.add_argument("--owner-approve", action="store_true", required=True)
    args = parser.parse_args()
    store = path_for()
    try:
        if args.action == "status":
            program = read_program(store)
            jobs = read_jobs(store)
            print("Milestones:")
            for task in program["tasks"]:
                print(task["id"], task["state"], "owner_verified=" + str(task["verified_by_owner"]))
            print("Ready:", ", ".join(t["id"] for t in ready_tasks(program)) or "none")
            print("Supervisor jobs:")
            for job in jobs:
                print(job["id"], job["task"], job["state"], job["plan_sha256"])
            print("No host tools were executed")
            return
        if args.action == "reconcile":
            print("Interrupted in-flight step records:", reconcile_interrupted(store))
            return
        if args.action == "create":
            result = create_job(store, args.task)
        elif args.action == "approve":
            result = approve_job(store, args.job, args.plan_sha256, owner_confirmed=args.owner_approve)
        elif args.action == "begin":
            result = begin_step(store, args.job, args.index)
        elif args.action == "finish":
            result = complete_step(store, args.job, args.index, args.evidence_sha256)
        elif args.action == "resume":
            result = resume_job(store, args.job, owner_confirmed=args.owner_approve)
        elif args.action == "finalize":
            result = finalize_job(store, args.job, owner_confirmed=args.owner_approve)
        else:
            result = verify_task(store, args.task, args.evidence_sha256, args.summary,
                                 owner_confirmed=args.owner_approve)
        print(json.dumps(result, indent=2))
        print("OWNER-SCOPED STATE CHANGE ONLY; NO TOOLS OR SOURCE CODE EXECUTED")
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        parser.exit(1, f"STOP: {type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    main()
