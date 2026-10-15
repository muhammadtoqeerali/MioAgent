"""Local-only REST API with bearer-token authentication for sensitive routes."""
import asyncio
import json
import secrets
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from mio.config import Settings
from mio.database import Task, create_database
from mio.workers import reset_interrupted_tasks, worker_loop


class TaskCreate(BaseModel):
    kind: Literal["demo_workflow", "workspace_inventory", "echo"] = "demo_workflow"
    prompt: str = Field(default="", max_length=4000)


def serialize_task(t: Task) -> dict:
    return {
        "id": t.id, "kind": t.kind, "prompt": t.prompt, "status": t.status,
        "progress": t.progress, "result": json.loads(t.result_json) if t.result_json else None,
        "error": t.error, "created_at": t.created_at.isoformat(),
        "updated_at": t.updated_at.isoformat(),
    }


def create_app(config: Settings | None = None) -> FastAPI:
    settings = config or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine, sessions = create_database(settings.mio_database_url)
        app.state.engine = engine
        app.state.sessions = sessions
        reset_interrupted_tasks(sessions)
        worker = asyncio.create_task(worker_loop(
            sessions, settings.mio_workspace_root, settings.mio_poll_seconds,
            settings.mio_demo_step_seconds))
        try:
            yield
        finally:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
            engine.dispose()

    app = FastAPI(title="MioAgent", version="0.1.0", lifespan=lifespan)

    def require_token(authorization: str | None = Header(default=None)) -> None:
        expected = f"Bearer {settings.mio_api_token}"
        if not authorization or not secrets.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail="Unauthorized")

    @app.get("/health")
    def health():
        return {"ok": True, "service": "mioagent-api", "version": "0.1.0"}

    @app.get("/api/status", dependencies=[Depends(require_token)])
    def current_status(request: Request):
        with request.app.state.sessions() as db:
            values = db.execute(select(Task.status, func.count()).group_by(Task.status)).all()
        return {
            "name": "MioAgent", "version": "0.1.0", "stage": "Phase 1 — Foundation",
            "mode": "local", "ai_model_connected": False, "voice_enabled": False,
            "computer_control_enabled": False,
            "task_counts": {name: count for name, count in values},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @app.get("/api/tasks", dependencies=[Depends(require_token)])
    def list_tasks(request: Request):
        with request.app.state.sessions() as db:
            tasks = db.scalars(select(Task).order_by(Task.created_at.desc()).limit(50)).all()
            return {"tasks": [serialize_task(task) for task in tasks]}

    @app.post("/api/tasks", status_code=status.HTTP_201_CREATED,
              dependencies=[Depends(require_token)])
    def create_task(payload: TaskCreate, request: Request):
        if payload.kind == "echo" and not payload.prompt.strip():
            raise HTTPException(status_code=422, detail="Echo text must not be empty")
        with request.app.state.sessions.begin() as db:
            task = Task(kind=payload.kind, prompt=payload.prompt.strip(), status="queued")
            db.add(task)
            db.flush()
            response = serialize_task(task)
        return response

    @app.get("/api/tasks/{task_id}", dependencies=[Depends(require_token)])
    def read_task(task_id: str, request: Request):
        with request.app.state.sessions() as db:
            task = db.get(Task, task_id)
            if task is None:
                raise HTTPException(status_code=404, detail="Task not found")
            return serialize_task(task)

    @app.post("/api/tasks/{task_id}/cancel", dependencies=[Depends(require_token)])
    def cancel_task(task_id: str, request: Request):
        with request.app.state.sessions.begin() as db:
            task = db.get(Task, task_id)
            if task is None:
                raise HTTPException(status_code=404, detail="Task not found")
            if task.status in {"queued", "running"}:
                task.status = "canceled"
                task.updated_at = datetime.now(timezone.utc)
            db.flush()
            return serialize_task(task)

    return app

