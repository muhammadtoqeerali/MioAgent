"""Durable local-only model repair proposals; never modify approved project bytes."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from mio.config import Settings
from mio.database import Project, Task, utcnow
from mio.llm import ModelRouter
from mio.model_fleet import FleetRouter, load_policy
from mio.project_mode import ProjectPolicyError, verify_existing_project
from mio.repair_proposal import is_failed_execution, repair_messages, validate_repair_reply


def latest_verification(db, project_id: str) -> Task | None:
    return db.scalar(select(Task).where(
        Task.kind == "project_verify", Task.prompt == project_id,
    ).order_by(Task.created_at.desc(), Task.id.desc()))


def failed_verification(db, project_id: str) -> Task:
    verification = latest_verification(db, project_id)
    if verification is None or verification.status != "completed" or not verification.result_json:
        raise ProjectPolicyError("A completed failed verification is required")
    try:
        result = json.loads(verification.result_json)
    except (TypeError, ValueError) as exc:
        raise ProjectPolicyError("Verification result is invalid") from exc
    if not is_failed_execution(result):
        raise ProjectPolicyError("Latest verification is not a failed sandbox execution")
    return verification


async def propose_project_repair(sessions: sessionmaker, task_id: str, settings: Settings) -> None:
    with sessions() as db:
        task = db.get(Task, task_id)
        if task is None or task.status == "canceled" or task.kind != "project_repair":
            return
        project = db.get(Project, task.prompt)
        if project is None or project.status != "completed" or not project.draft_json:
            raise ProjectPolicyError("Repair requires an approved completed project")
        verification = failed_verification(db, project.id)
        source_draft = json.loads(project.draft_json)
        project_id, requirements = project.id, project.requirements
        verified_id = verification.id
        failure = json.loads(verification.result_json)
    # No model calls for modified/tampered source artifacts.
    if verify_existing_project(settings.mio_project_root, project_id, source_draft) is None:
        raise ProjectPolicyError("Original approved artifact is missing")
    messages = repair_messages(requirements, source_draft, failure)
    local_only = settings.model_copy(update={"mio_allow_cloud": False, "mio_model_route": "local"})
    model = FleetRouter(local_only, "repair") if load_policy() else ModelRouter(local_only)
    for attempt in range(2):
        completion = await model.complete(messages, max_tokens=2048)
        try:
            proposal = validate_repair_reply(completion.text, source_draft)
            break
        except ProjectPolicyError:
            if attempt or not isinstance(model, FleetRouter) or not model.advance():
                raise
            # Never forward malformed full candidate or private credentials to the next model.
            messages.append({"role": "user", "content":
                             "The proposed change failed local policy validation. "
                             "Return one valid repair JSON object modifying only approved app source."})
    proposal.update({"verification_task_id": verified_id, "model": completion.model,
                     "provider": completion.provider})
    with sessions.begin() as db:
        task = db.get(Task, task_id)
        project = db.get(Project, project_id)
        if task is None or task.status == "canceled" or project is None:
            return
        if project.status != "completed" or latest_verification(db, project_id).id != verified_id:
            raise ProjectPolicyError("Project verification changed during repair proposal")
        task.result_json = json.dumps(proposal, ensure_ascii=False)
        task.status = "completed"
        task.progress = 100
        task.updated_at = utcnow()
