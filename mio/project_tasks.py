"""Durable draft and approved artifact tasks. No model-generated code is executed."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from mio.config import Settings
from mio.database import Project, Task, utcnow
from mio.llm import ModelRouter
from mio.model_fleet import FleetRouter, load_policy
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


DRAFT_RETRIES = 2

DRAFT_INSTRUCTIONS = (
    "\n\nIMPORTANT DELIVERY REQUIREMENT: Return one JSON object with exactly "
    "the fields plan and files. plan is an array of short step strings. "
    "files MUST be a NONEMPTY array of objects with path and content strings. "
    "Generate working APPLICATION source: at least one .py implementation file; "
    "do not provide an explanation or empty files. Use 1-3 small application files. "
    "If USER-OWNED IMMUTABLE TESTS appear in requirements, the trusted operator "
    "adds those separately; you do not need to reproduce test files. "
    "Keep generated code syntactically correct and under the documented budgets."
)


def _draft_retry_message(reason: str) -> str:
    """Give only bounded validation feedback, never model-generated content."""
    # Validation exceptions come from trusted policy text, not from an upstream
    # HTTP body or the original model output. No arbitrary error text enters prompt.
    permitted = {
        "Draft must contain 1 to 6 files": "Include 1-3 real application file objects.",
        "Plan must contain 1 to 8 steps": "Include 1-5 short plan step strings.",
        "Model did not produce valid JSON": "Return one complete valid JSON object.",
        "Model output must be a JSON object": "Return a JSON object, not a list.",
    }
    instruction = next((v for k, v in permitted.items() if reason.startswith(k)),
                       "Correct the schema and syntax of the application draft.")
    return (
        "Your previous draft was rejected by the trusted local validator. "
        + instruction + " Return ONLY complete JSON with plan and a nonempty files array. "
        "Each file needs path and full source content, not placeholders. "
        "Do not claim tests were run. The original user acceptance tests are inserted "
        "separately and must not be changed."
    )


async def generate_validated_draft(router: ModelRouter, requirements: str) -> tuple[dict, object, int]:
    """Bounded schema repair. No tool execution, no test mutation, no HTTP retry storm."""
    messages = [
        {"role": "system", "content": PROJECT_PLANNER + DRAFT_INSTRUCTIONS},
        {"role": "user", "content": requirements},
    ]
    for attempt in range(1, DRAFT_RETRIES + 1):
        completion = await router.complete(messages, max_tokens=3072)
        try:
            candidate = validate_draft(completion.text)
            # The trusted preapproval acceptance endpoint will supply the tests.
            # A draft without actual application Python is never enough here.
            if not any(f["path"].endswith(".py")
                       and not Path(f["path"]).name.startswith("test_")
                       for f in candidate["files"]):
                raise ProjectPolicyError("Draft has no application Python source")
            return candidate, completion, attempt
        except ProjectPolicyError as exc:
            if attempt == DRAFT_RETRIES:
                raise ProjectPolicyError(
                    f"Model draft invalid after {DRAFT_RETRIES} attempts: {exc}"
                ) from exc
            # Escalate malformed source to a second benchmarked model when available.
            # Otherwise retry the same local model exactly once as before.
            if isinstance(router, FleetRouter):
                router.advance()
            messages.append({"role": "user", "content": _draft_retry_message(str(exc))})
    raise ProjectPolicyError("Draft retry limit reached")


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
        router = FleetRouter(local_only, "coding") if load_policy() else ModelRouter(local_only)
        approved_candidate, completion, attempts = await generate_validated_draft(
            router, requirements,
        )
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
                                           "provider": completion.provider,
                                           "generation_attempts": attempts})
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
