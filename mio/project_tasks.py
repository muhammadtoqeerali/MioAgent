"""Durable draft and approved artifact tasks. No model-generated code is executed."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from mio.config import Settings
from mio.database import Project, Task, utcnow
from mio.llm import ModelRouter
from mio.project_mode import (
    PROJECT_PLANNER,
    ProjectPolicyError,
    apply_draft,
    validate_draft,
    verify_existing_project,
)


def project_task_status(sessions: sessionmaker, task_id: str) -> str:
    with sessions() as db:
        task = db.get(Task, task_id)
        return task.status if task else "unknown"


def mark_project_failure(sessions: sessionmaker, project_id: str, error: str) -> None:
    with sessions.begin() as db:
        project = db.get(Project, project_id)
        if project is not None and project.status not in {"completed", "canceled"}:
            project.status = "failed"
            project.error = error[:500]
            project.updated_at = utcnow()


async def draft_project(sessions: sessionmaker, task_id: str, settings: Settings) -> None:
    with sessions() as db:
        task = db.get(Task, task_id)
        if task is None or task.status == "canceled":
            return
        project = db.get(Project, task.prompt)
        if project is None or project.status != "drafting":
            raise ValueError("Project draft is no longer active")
        project_id, requirements = project.id, project.requirements
    try:
        # Project Mode never selects paid APIs. This policy is enforced at the model client.
        local_only = settings.model_copy(update={"mio_allow_cloud": False,
                                                  "mio_model_route": "local"})
        router = ModelRouter(local_only)
        completion = await router.complete([
            {"role": "system", "content": PROJECT_PLANNER},
            {"role": "user", "content": requirements},
        ], max_tokens=2048)
        approved_candidate = validate_draft(completion.text)
        with sessions.begin() as db:
            task = db.get(Task, task_id)
            project = db.get(Project, project_id)
            if task is None or task.status == "canceled" or project is None:
                return
            if project.status != "drafting":
                return
            project.draft_json = json.dumps(approved_candidate, ensure_ascii=False)
            project.status = "review"
            project.updated_at = utcnow()
            task.result_json = json.dumps({"stage": "awaiting_approval",
                                           "file_count": approved_candidate["file_count"],
                                           "total_bytes": approved_candidate["total_bytes"],
                                           "checks": approved_candidate["checks"],
                                           "model": completion.model,
                                           "provider": completion.provider})
            task.progress = 100
            task.status = "completed"
            task.updated_at = utcnow()
    except Exception as exc:
        mark_project_failure(sessions, project_id, str(exc))
        raise


def apply_project(sessions: sessionmaker, task_id: str, root: Path) -> None:
    with sessions() as db:
        task = db.get(Task, task_id)
        if task is None or task.status == "canceled":
            return
        project = db.get(Project, task.prompt)
        if project is None or project.status != "applying" or not project.draft_json:
            raise ValueError("Project has no approved draft")
        project_id = project.id
        candidate = json.loads(project.draft_json)
    try:
        result = verify_existing_project(root, project_id, candidate)
        if result is None:
            if project_task_status(sessions, task_id) == "canceled":
                return
            result = apply_draft(root, project_id, candidate)
        with sessions.begin() as db:
            task = db.get(Task, task_id)
            project = db.get(Project, project_id)
            if task is None or project is None:
                return
            # A cancellation after filesystem rename is represented truthfully below:
            # artifact can exist, but the task remains canceled (never claim completion).
            if task.status == "canceled":
                project.workspace_path = result["workspace"]
                project.status = "canceled"
                project.updated_at = utcnow()
                return
            project.workspace_path = result["workspace"]
            project.status = "completed"
            project.updated_at = utcnow()
            task.result_json = json.dumps(result)
            task.status = "completed"
            task.progress = 100
            task.updated_at = utcnow()
    except (OSError, ProjectPolicyError, ValueError, KeyError) as exc:
        mark_project_failure(sessions, project_id, str(exc))
        raise


def mark_project_canceled_for_task(db, task_id: str) -> None:
    """Synchronize project state when its running/queued task is canceled."""
    project = db.scalar(select(Project).where(
        (Project.draft_task_id == task_id) | (Project.apply_task_id == task_id)
    ))
    if project is not None and project.status in {"drafting", "applying"}:
        project.status = "canceled"
        project.updated_at = utcnow()
