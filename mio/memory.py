"""User-approved durable memory, retrieved with predictable lexical matching.

This is explicitly NOT embedding/vector search or silent autonomous learning.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from mio.database import ChatMessage, MemoryNote

STOPWORDS = {"a", "the", "and", "of", "to", "is", "in", "for", "can", "how", "i", "you"}


def tokens(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9_]{2,}", text.lower()) if word not in STOPWORDS}


def relevant_notes(sessions: sessionmaker, query: str, limit: int = 4) -> list[str]:
    query_tokens = tokens(query)
    if not query_tokens:
        return []
    with sessions() as db:
        notes = db.scalars(select(MemoryNote).order_by(MemoryNote.created_at.desc()).limit(500)).all()
    scored = []
    for note in notes:
        score = len(query_tokens & tokens(note.content))
        if score:
            scored.append((score, note.created_at, note.content))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [content for _, _, content in scored[:limit]]


def recent_history(sessions: sessionmaker, conversation_id: str,
                   message_id: str, limit: int = 20) -> list[dict[str, str]]:
    """Only include messages up to this request, never future queued user prompts."""
    with sessions() as db:
        target = db.get(ChatMessage, message_id)
        if target is None or target.conversation_id != conversation_id:
            raise ValueError("Missing conversation message")
        rows = db.scalars(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id,
                   ChatMessage.created_at <= target.created_at)
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(limit)
        ).all()
    rows.reverse()
    history = [{"role": row.role, "content": row.content} for row in rows]
    if not history or history[-1]["content"] != target.content:
        history.append({"role": "user", "content": target.content})
    return history
