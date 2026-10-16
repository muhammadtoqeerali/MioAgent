"""Local-first FastAPI backend with authenticated task and AI conversation endpoints."""

import asyncio
import json
import secrets
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from mio.config import Settings
from mio.database import (
    AIJob,
    ChatMessage,
    Conversation,
    MemoryNote,
    Project,
    Task,
    create_database,
    utcnow,
)
from mio.llm import ModelRouter
from mio.project_mode import MAX_REQUIREMENTS, ProjectPolicyError, check_private_root
from mio.project_tasks import mark_project_canceled_for_task
from mio.workers import reset_interrupted_tasks, worker_loop


class TaskCreate(BaseModel):
    kind: Literal["demo_workflow", "workspace_inventory", "echo"] = "demo_workflow"
    prompt: str = Field(default="", max_length=4000)


class AskCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=12000)
    conversation_id: str | None = Field(default=None, max_length=36)


class ProjectCreate(BaseModel):
    title: str = Field(min_length=3, max_length=140)
    requirements: str = Field(min_length=20, max_length=MAX_REQUIREMENTS)


class ProjectApply(BaseModel):
    approved: Literal[True]


def serialize_project(project: Project, *, include_draft: bool = False) -> dict:
    result = {
        "id": project.id, "title": project.title, "requirements": project.requirements,
        "status": project.status, "workspace": project.workspace_path,
        "draft_task_id": project.draft_task_id, "apply_task_id": project.apply_task_id,
        "error": project.error, "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }
    if include_draft:
        result["draft"] = json.loads(project.draft_json) if project.draft_json else None
    return result


class RememberCreate(BaseModel):
    content: str = Field(min_length=3, max_length=2000)


def serialize_task(t: Task) -> dict:
    return {
        "id": t.id, "kind": t.kind, "prompt": t.prompt, "status": t.status,
        "progress": t.progress, "result": json.loads(t.result_json) if t.result_json else None,
        "error": t.error, "created_at": t.created_at.isoformat(),
        "updated_at": t.updated_at.isoformat(),
    }


def serialize_message(m: ChatMessage) -> dict:
    return {"id": m.id, "role": m.role, "content": m.content,
            "task_id": m.task_id, "created_at": m.created_at.isoformat()}


def create_app(config: Settings | None = None) -> FastAPI:
    settings = config or Settings()
    router = ModelRouter(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine, sessions = create_database(settings.mio_database_url)
        app.state.engine = engine
        app.state.sessions = sessions
        reset_interrupted_tasks(sessions)
        worker = asyncio.create_task(worker_loop(
            sessions, settings.mio_workspace_root, settings.mio_poll_seconds,
            settings.mio_demo_step_seconds, settings))
        try:
            yield
        finally:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
            engine.dispose()

    app = FastAPI(title="MioAgent", version="0.2.0", lifespan=lifespan)

    def require_token(authorization: str | None = Header(default=None)) -> None:
        expected = f"Bearer {settings.mio_api_token}"
        if not authorization or not secrets.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail="Unauthorized")

    @app.get("/health")
    def health():
        return {"ok": True, "service": "mioagent-api", "version": "0.2.0"}

    @app.get("/api/status", dependencies=[Depends(require_token)])
    async def current_status(request: Request):
        with request.app.state.sessions() as db:
            values = db.execute(select(Task.status, func.count()).group_by(Task.status)).all()
        model_state = await router.probe()
        return {
            "name": "MioAgent", "version": "0.2.0", "stage": "Phase 2 — Intelligence",
            "mode": "local", "ai_model_connected": model_state["local_reachable"],
            "ai_model_configured": model_state["configured"],
            "voice_enabled": False, "computer_control_enabled": False,
            "project_mode_enabled": settings.mio_enable_project_mode,
            "project_mode_capability": "reviewed_source_drafts_only" if settings.mio_enable_project_mode else "off",
            "task_counts": {name: count for name, count in values},
            "timestamp": datetime.now(UTC).isoformat(),
        }

    @app.get("/api/assistant/status", dependencies=[Depends(require_token)])
    async def assistant_status():
        return await router.probe()

    @app.get("/api/assistant/conversations", dependencies=[Depends(require_token)])
    def list_conversations(request: Request):
        with request.app.state.sessions() as db:
            items = db.scalars(
                select(Conversation).order_by(Conversation.updated_at.desc()).limit(100)
            ).all()
            return {"conversations": [
                {"id": c.id, "title": c.title, "updated_at": c.updated_at.isoformat()}
                for c in items
            ]}

    @app.get("/api/assistant/conversations/{conversation_id}",
             dependencies=[Depends(require_token)])
    def get_conversation(conversation_id: str, request: Request):
        with request.app.state.sessions() as db:
            conversation = db.get(Conversation, conversation_id)
            if conversation is None:
                raise HTTPException(status_code=404, detail="Conversation not found")
            messages = db.scalars(
                select(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
                .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc()).limit(100)
            ).all()
            return {"id": conversation.id, "title": conversation.title,
                    "messages": [serialize_message(m) for m in messages]}

    @app.post("/api/assistant/ask", status_code=202,
              dependencies=[Depends(require_token)])
    def ask(payload: AskCreate, request: Request):
        if not router.configured():
            raise HTTPException(status_code=409, detail="Configure a local model first")
        content = payload.prompt.strip()
        if not content:
            raise HTTPException(status_code=422, detail="Empty prompt")
        with request.app.state.sessions.begin() as db:
            if payload.conversation_id:
                conversation = db.get(Conversation, payload.conversation_id)
                if conversation is None:
                    raise HTTPException(status_code=404, detail="Conversation not found")
            else:
                conversation = Conversation(title=content[:100])
                db.add(conversation)
                db.flush()
            message = ChatMessage(conversation_id=conversation.id, role="user", content=content)
            db.add(message)
            task = Task(kind="ai_chat", prompt=content, status="queued")
            db.add(task)
            db.flush()
            db.add(AIJob(task_id=task.id, conversation_id=conversation.id, message_id=message.id))
            conversation.updated_at = utcnow()
            answer = {"conversation_id": conversation.id, "task_id": task.id, "status": "queued"}
        return answer

    @app.get("/api/assistant/memories", dependencies=[Depends(require_token)])
    def list_memories(request: Request):
        with request.app.state.sessions() as db:
            notes = db.scalars(
                select(MemoryNote).order_by(MemoryNote.created_at.desc()).limit(100)
            ).all()
            return {"memories": [{"id": n.id, "content": n.content} for n in notes]}

    @app.post("/api/assistant/memories", status_code=201,
              dependencies=[Depends(require_token)])
    def remember(payload: RememberCreate, request: Request):
        content = payload.content.strip()
        if len(content) < 3:
            raise HTTPException(status_code=422, detail="Memory note too short")
        with request.app.state.sessions.begin() as db:
            note = MemoryNote(content=content)
            db.add(note)
            db.flush()
            return {"id": note.id, "content": note.content}

    @app.delete("/api/assistant/memories/{memory_id}",
                dependencies=[Depends(require_token)])
    def delete_memory(memory_id: str, request: Request):
        with request.app.state.sessions.begin() as db:
            note = db.get(MemoryNote, memory_id)
            if note is None:
                raise HTTPException(status_code=404, detail="Memory not found")
            db.delete(note)
            return {"deleted": True}

    def require_project_feature() -> None:
        if not settings.mio_enable_project_mode:
            raise HTTPException(status_code=409, detail="Project Mode disabled by administrator")

    @app.get("/api/projects", dependencies=[Depends(require_token)])
    def list_projects(request: Request):
        require_project_feature()
        with request.app.state.sessions() as db:
            rows = db.scalars(select(Project).order_by(Project.created_at.desc()).limit(50)).all()
            return {"projects": [serialize_project(row) for row in rows]}

    @app.get("/api/projects/{project_id}", dependencies=[Depends(require_token)])
    def get_project(project_id: str, request: Request):
        require_project_feature()
        with request.app.state.sessions() as db:
            project = db.get(Project, project_id)
            if project is None:
                raise HTTPException(status_code=404, detail="Project not found")
            return serialize_project(project, include_draft=True)

    @app.post("/api/projects", status_code=202, dependencies=[Depends(require_token)])
    def create_project(payload: ProjectCreate, request: Request):
        require_project_feature()
        if not router.configured():
            raise HTTPException(status_code=409, detail="Configure a local AI model first")
        if not settings.mio_local_model:
            raise HTTPException(status_code=409, detail="Project Mode requires a local model")
        try:
            check_private_root(settings.mio_project_root)
        except (OSError, ProjectPolicyError) as exc:
            raise HTTPException(status_code=409, detail=f"Project storage not ready: {exc}") from exc
        with request.app.state.sessions.begin() as db:
            project = Project(title=payload.title.strip(),
                              requirements=payload.requirements.strip(), status="drafting")
            db.add(project)
            db.flush()
            task = Task(kind="project_draft", prompt=project.id, status="queued")
            db.add(task)
            db.flush()
            project.draft_task_id = task.id
            return serialize_project(project)

    @app.post("/api/projects/{project_id}/apply", status_code=202,
              dependencies=[Depends(require_token)])
    def approve_project(project_id: str, payload: ProjectApply, request: Request):
        require_project_feature()
        with request.app.state.sessions.begin() as db:
            project = db.get(Project, project_id)
            if project is None:
                raise HTTPException(status_code=404, detail="Project not found")
            if project.status != "review" or not project.draft_json:
                raise HTTPException(status_code=409, detail="Project is not awaiting approval")
            project.status = "applying"
            project.updated_at = utcnow()
            task = Task(kind="project_apply", prompt=project.id, status="queued")
            db.add(task)
            db.flush()
            project.apply_task_id = task.id
            return serialize_project(project)

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
                task.updated_at = datetime.now(UTC)
                mark_project_canceled_for_task(db, task_id)
            db.flush()
            return serialize_task(task)

    return app
