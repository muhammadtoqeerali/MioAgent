"""Persistent, deliberately restricted task worker for Phase 1.

Only three allowlisted demonstration/inspection task types are executable.
No arbitrary code execution, shell access, web browsing, or LLM agent calls exist yet.
"""
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from mio.config import Settings
from mio.database import AIJob, ChatMessage, Task, utcnow
from mio.llm import ModelRouter
from mio.memory import recent_history, relevant_notes
from mio.model_fleet import FleetRouter, load_policy
from mio.project_tasks import apply_project, draft_project
from mio.project_verification_tasks import verify_project_task
from mio.repair_tasks import propose_project_repair
from mio.supervisor import supervise

IGNORED_DIRS = {
    ".git", ".venv", "node_modules", ".next", "__pycache__", ".mypy_cache",
    ".pytest_cache", "data", "secrets", "private", ".cache",
}
IGNORED_FILES = {".env", ".env.local", ".npmrc", "id_rsa", "id_ed25519"}
IGNORED_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".sqlite", ".db"}


def inventory_workspace(root: Path, max_entries: int = 200) -> dict:
    """List non-sensitive filenames under a designated read-only workspace.

    Avoid symlinks and hidden folders. This is an inventory, not arbitrary file reading.
    """
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Workspace root must be a directory")
    entries: list[str] = []
    total = 0
    for base, directories, files in os.walk(root, followlinks=False):
        directories[:] = sorted(
            d for d in directories
            if d not in IGNORED_DIRS and not d.startswith(".")
            and not (Path(base) / d).is_symlink()
        )
        for filename in sorted(files):
            item = Path(base) / filename
            if (item.is_symlink() or filename.startswith(".")
                    or filename in IGNORED_FILES or item.suffix.lower() in IGNORED_SUFFIXES):
                continue
            total += 1
            if len(entries) < max_entries:
                entries.append(str(item.relative_to(root)))
    return {"root": str(root), "sample_files": entries, "visible_file_count": total,
            "truncated": total > max_entries}


def reset_interrupted_tasks(sessions: sessionmaker) -> None:
    # Phase-1 tasks are intentionally idempotent; safe to requeue after an unclean restart.
    with sessions.begin() as db:
        db.execute(update(Task).where(Task.status == "running").values(
            status="queued", progress=0, error=None, updated_at=datetime.now(UTC)
        ))


def claim_task(sessions: sessionmaker) -> str | None:
    with sessions.begin() as db:
        task = db.scalar(
            select(Task).where(Task.status == "queued")
            .order_by(Task.created_at, Task.id).limit(1).with_for_update(skip_locked=True)
        )
        if task is None:
            return None
        task.status = "running"
        task.updated_at = datetime.now(UTC)
        db.flush()
        return task.id


def get_task(sessions: sessionmaker, task_id: str) -> Task | None:
    with sessions() as db:
        return db.get(Task, task_id)


def update_task(sessions: sessionmaker, task_id: str, *, progress: int | None = None,
                result: dict | None = None, error: str | None = None,
                status: str | None = None) -> bool:
    with sessions.begin() as db:
        task = db.get(Task, task_id)
        if task is None or task.status == "canceled":
            return False
        if progress is not None:
            task.progress = progress
        if result is not None:
            task.result_json = json.dumps(result, ensure_ascii=False)
        if error is not None:
            task.error = error[:2000]
        if status is not None:
            task.status = status
        task.updated_at = datetime.now(UTC)
        return True


async def run_ai_task(sessions: sessionmaker, task_id: str, router: ModelRouter) -> None:
    with sessions() as db:
        job = db.get(AIJob, task_id)
        if job is None:
            raise ValueError("Missing AI job metadata")
        conversation_id, message_id = job.conversation_id, job.message_id
        existing = db.scalar(select(ChatMessage).where(ChatMessage.task_id == task_id))
        if existing is not None:
            update_task(sessions, task_id, progress=100, status="completed",
                        result={"answer": existing.content, "resumed": True})
            return
    history = recent_history(sessions, conversation_id, message_id)
    prompt = history[-1]["content"]
    notes = relevant_notes(sessions, prompt)
    update_task(sessions, task_id, progress=10,
                result={"stage": "planning", "note": "Descriptive plan only; no tools execute"})

    async def save_plan(plan, completion):
        update_task(sessions, task_id, progress=45, result={
            "stage": "responding", "plan": plan,
            "planner_model": completion.model, "planner_provider": completion.provider,
        })

    task_router = FleetRouter(router.settings, "chat") if load_policy() else router
    result = await supervise(task_router, history, notes, on_plan=save_plan)
    # The user may have canceled while the model was responding. Commit task and
    # assistant message atomically so the system never duplicates completed turns.
    with sessions.begin() as db:
        task = db.get(Task, task_id)
        if task is None or task.status == "canceled":
            return
        already = db.scalar(select(ChatMessage).where(ChatMessage.task_id == task_id))
        if already is None:
            db.add(ChatMessage(conversation_id=conversation_id, role="assistant",
                               content=result.answer, task_id=task_id))
        task.result_json = json.dumps({
            "stage": "completed", "plan": result.plan, "answer": result.answer,
            "model": result.model, "provider": result.provider,
            "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
        }, ensure_ascii=False)
        task.status, task.progress, task.updated_at = "completed", 100, utcnow()


async def run_task(sessions: sessionmaker, task_id: str, workspace: Path,
                   step_seconds: float, router: ModelRouter | None = None) -> None:
    task = get_task(sessions, task_id)
    if task is None:
        return
    try:
        if task.kind == "project_draft":
            if router is None:
                raise ValueError("Project Mode requires a configured model")
            # Router carries validated administrator settings.
            await draft_project(sessions, task_id, router.settings)
        elif task.kind == "project_apply":
            if router is None:
                raise ValueError("Project Mode requires configured settings")
            await asyncio.to_thread(apply_project, sessions, task_id,
                                    router.settings.mio_project_root)
        elif task.kind == "project_verify":
            if router is None or not router.settings.mio_enable_sandbox_verify:
                raise ValueError("Sandbox verification is disabled")
            await asyncio.to_thread(verify_project_task, sessions, task_id,
                                    router.settings.mio_project_root)
        elif task.kind == "project_repair":
            if router is None or not router.settings.mio_enable_sandbox_verify:
                raise ValueError("Sandbox repair proposals are disabled")
            await propose_project_repair(sessions, task_id, router.settings)
        elif task.kind == "ai_chat":
            if router is None:
                raise ValueError("Model router not configured")
            await run_ai_task(sessions, task_id, router)
        elif task.kind == "demo_workflow":
            steps = ["Analyze task", "Prepare work plan", "Execute demo steps",
                     "Verify result", "Prepare summary"]
            for i, step in enumerate(steps, start=1):
                if get_task(sessions, task_id).status == "canceled":
                    return
                update_task(sessions, task_id, progress=i * 20,
                            result={"last_step": step, "steps_total": len(steps),
                                    "note": "Demonstration only; no AI model is being called."})
                await asyncio.sleep(step_seconds)
            update_task(sessions, task_id, status="completed")
        elif task.kind == "workspace_inventory":
            report = await asyncio.to_thread(inventory_workspace, workspace)
            update_task(sessions, task_id, progress=100, result=report, status="completed")
        elif task.kind == "echo":
            update_task(sessions, task_id, progress=100,
                        result={"text": task.prompt}, status="completed")
        else:
            raise ValueError("Task kind is not permitted")
    except Exception as exc:  # noqa: BLE001 — worker must record unexpected failures
        update_task(sessions, task_id, status="failed", error=str(exc))


async def worker_loop(sessions: sessionmaker, workspace: Path, poll_seconds: float,
                      step_seconds: float, settings: Settings | None = None) -> None:
    router = ModelRouter(settings) if settings is not None else None
    while True:
        task_id = await asyncio.to_thread(claim_task, sessions)
        if task_id is None:
            await asyncio.sleep(poll_seconds)
            continue
        await run_task(sessions, task_id, workspace, step_seconds, router)
