"""Persist real isolated unittest results for explicitly approved projects."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from mio.database import Project, Task, utcnow
from mio.sandbox_verify import verify_approved_project


def verify_project_task(sessions: sessionmaker, task_id: str, root: Path) -> None:
    with sessions() as db:
        task = db.get(Task, task_id)
        if task is None or task.status == "canceled" or task.kind != "project_verify":
            return
        project = db.get(Project, task.prompt)
        if project is None or project.status != "completed" or not project.draft_json:
            raise ValueError("Verification requires a completed, approved project")
        project_id, draft = project.id, json.loads(project.draft_json)

    result = verify_approved_project(root, project_id, draft)
    with sessions.begin() as db:
        task = db.get(Task, task_id)
        if task is None or task.status == "canceled":
            return
        task.result_json = json.dumps(result, ensure_ascii=False)
        task.status = "completed"  # Test failures are recorded truthfully in result.passed.
        task.progress = 100
        task.updated_at = utcnow()
