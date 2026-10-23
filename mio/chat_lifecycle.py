"""Explicit archive/restore and irreversible deletion of owner chat records.

No model output can invoke these routes. All operations require the native API bearer token.
Only completed/failed/canceled conversations may be deleted; pending tasks remain intact.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Mapped, mapped_column

from mio.database import AIJob, Base, ChatMessage, Conversation, Task, utcnow


class ArchivedChat(Base):
    __tablename__ = "archived_chats"

    conversation_id: Mapped[str] = mapped_column(primary_key=True)
    archived_at: Mapped[str] = mapped_column(nullable=False)


def is_archived(db, conversation_id: str) -> bool:
    return db.get(ArchivedChat, conversation_id) is not None


def list_chat_query(*, archived: bool = False):
    ids = select(ArchivedChat.conversation_id)
    return (select(Conversation)
            .where(Conversation.id.in_(ids) if archived else ~Conversation.id.in_(ids))
            .order_by(Conversation.updated_at.desc()).limit(100))


def _get_chat(db, conversation_id: str) -> Conversation:
    row = db.get(Conversation, conversation_id)
    if row is None:
        raise HTTPException(404, detail="Conversation not found")
    return row


def register_chat_lifecycle(app: FastAPI, require_token: Callable) -> None:
    auth = [Depends(require_token)]

    @app.post("/api/assistant/conversations/{conversation_id}/archive", dependencies=auth)
    def archive(conversation_id: str, request: Request):
        with request.app.state.sessions.begin() as db:
            _get_chat(db, conversation_id)
            if not is_archived(db, conversation_id):
                db.add(ArchivedChat(conversation_id=conversation_id, archived_at=utcnow().isoformat()))
        return {"archived": True}

    @app.post("/api/assistant/conversations/{conversation_id}/restore", dependencies=auth)
    def restore(conversation_id: str, request: Request):
        with request.app.state.sessions.begin() as db:
            _get_chat(db, conversation_id)
            db.execute(delete(ArchivedChat).where(ArchivedChat.conversation_id == conversation_id))
        return {"archived": False}

    @app.delete("/api/assistant/conversations/{conversation_id}", dependencies=auth)
    def erase(conversation_id: str, request: Request):
        """Delete DB messages, job links and chat-only tasks; refuse in-flight work.

        Image jobs live in a distinct Studio store and are not chat-linked yet.
        """
        with request.app.state.sessions() as db:
            # Serialize deletion against SQLite worker claims. No network/model awaits.
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            conversation = _get_chat(db, conversation_id)
            task_ids = list(db.scalars(select(AIJob.task_id).where(AIJob.conversation_id == conversation_id)))
            if task_ids:
                active = db.scalars(select(Task.id).where(
                    Task.id.in_(task_ids), Task.status.in_(["queued", "running"]))).first()
                if active:
                    raise HTTPException(409, detail="This chat has a queued or running task; finish or cancel it first")
            # IMG3A: owner deletion includes associated image-turn history.
            from mio.omni_images import ImageTurn
            db.execute(delete(ImageTurn).where(ImageTurn.scope == "chat", ImageTurn.scope_id == conversation_id))
            db.execute(delete(ChatMessage).where(ChatMessage.conversation_id == conversation_id))
            db.execute(delete(AIJob).where(AIJob.conversation_id == conversation_id))
            if task_ids:
                db.execute(delete(Task).where(Task.id.in_(task_ids)))
            db.execute(delete(ArchivedChat).where(ArchivedChat.conversation_id == conversation_id))
            db.delete(conversation)
            db.commit()
        return {"deleted": True, "chat_tasks_deleted": len(task_ids),
                "note": "Separate Studio image jobs are not linked to conversations and are not deleted."}
