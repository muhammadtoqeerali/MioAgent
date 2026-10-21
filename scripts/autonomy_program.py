"""Manage local, owner-approved backlog and optional model planning proposals.

Planning output is untrusted DATA: this CLI cannot execute shell commands, write
project code, grant network/browser access, or commit to Git.
"""

from __future__ import annotations

import argparse
import asyncio
import json

from mio.autonomy_program import (
    initialize,
    parse_proposal,
    path_for,
    read_program,
    ready_tasks,
    save_proposal,
)


def _plan_prompt(task: dict) -> str:
    return (
        "Return JSON ONLY with key steps: an array of 3-7 bounded, concrete engineering steps. "
        "These are recommendations for an owner to review, NOT commands to execute. "
        "Specify real tests and independent acceptance gates; do not claim any work was done. "
        "Do not request credentials, system-level tools, automatic deployment or model downloads.\n"
        f"TASK: {task['title']}\nROLE: {task['role']}\n"
        f"ACCEPTANCE CRITERIA: {task['acceptance']}\n"
        f"DEPENDENCIES: {', '.join(task['depends_on']) or 'none'}"
    )


async def _model_plan(task: dict) -> tuple[list[str], str]:
    from mio.config import Settings
    from mio.model_fleet import FleetRouter
    from scripts.native_runtime import get_token, load_model_config

    config = load_model_config()
    settings = Settings(
        mio_api_token=get_token(), mio_local_model=config.get("MIO_LOCAL_MODEL", ""),
        mio_model_route="local", mio_allow_cloud=False,
    )
    router = FleetRouter(settings, "planning")
    result = await router.complete([
        {"role": "system", "content": "You create strictly bounded engineering plans. No tool execution."},
        {"role": "user", "content": _plan_prompt(task)},
    ], max_tokens=650)
    return parse_proposal(result.text), result.model


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "status", "ready", "propose"))
    parser.add_argument("task", nargs="?")
    parser.add_argument("--base-commit", default=None)
    args = parser.parse_args()
    store = path_for()
    if args.action == "init":
        if not args.base_commit:
            parser.error("init requires --base-commit")
        data, created = initialize(store, args.base_commit)
        print("CREATED" if created else "EXISTS", "durable owner-controlled autonomy backlog")
        print("Tasks:", len(data["tasks"]), "Git baseline:", data["base_commit"])
        return
    data = read_program(store)
    if args.action == "ready":
        ready = ready_tasks(data)
        print("Ready for owner-reviewed planning:")
        for task in ready:
            print(" ", task["id"], "—", task["title"])
        return
    if args.action == "status":
        for task in data["tasks"]:
            blocked = [x for x in task["depends_on"] if not any(
                t["id"] == x and t["verified_by_owner"] for t in data["tasks"]
            )]
            print(task["id"], "|", task["state"], "| blocked by:", ", ".join(blocked) or "none")
        return
    if not args.task:
        parser.error("propose requires a task id")
    task = next((t for t in ready_tasks(data) if t["id"] == args.task), None)
    if task is None:
        parser.error("Task is blocked or has an existing proposal")
    steps, model = asyncio.run(_model_plan(task))
    saved = save_proposal(store, args.task, steps, model)
    print(json.dumps({"task": saved["id"], "model": model,
                      "proposal": saved["proposal"], "review_required": True}, indent=2))
    print("NO ACTIONS EXECUTED. Owner review required before any implementation.")


if __name__ == "__main__":
    main()
