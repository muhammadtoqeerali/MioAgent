"""IMG3A: owner-authenticated native conversation image turns.

Stores turn metadata in an additive SQL table. Reuses FLUX.2 Image Lab inference
and the existing owner-private Studio attachments. No filesystem arguments, model
routing permission changes, source application or automatic remote network access.
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
import stat
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from mio.database import Base, ChatMessage, Conversation, utcnow
from mio.studio_api import _jobs, _read_job, _studio
from mio.studio_autoroute import route_intent
from mio.studio_files import StudioError, read_attachment, save_attachment
from mio.work_core import WorkStop, project_info

HEX32 = re.compile(r"[0-9a-f]{32}\Z")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
PNG = b"\x89PNG\r\n\x1a\n"
MARKER = "MIO_IMAGE_TURN:"
MAX_ASSET = 8 * 1024 * 1024
EDIT = re.compile(r"\b(edit|change|replace|remove|recolor|modify|alter|adjust|make it|make the|" 
                  r"turn (?:it|the)|same (?:person|image|picture|photo)|" 
                  r"background|jacket|shirt|hair|color|colour|add (?:a|an|the))\b", re.IGNORECASE)
TEXT_EDIT_CONTEXT = re.compile(
    r"\b(project|software|code|deadline|task|document|report|repository|policy|"
    r"python|javascript|typescript|file|function|script|source|module|tests?|"
    r"git|github|commit|branch|website|webpage|button|configuration|config|"
    r"spreadsheet|email|pdf|paragraph)\b", re.IGNORECASE)
CREATE = re.compile(r"\b(generate|create|draw|render|paint|illustrate|make|produce|design)\b.{0,100}"
                    r"\b(image|photo|picture|portrait|illustration|artwork|logo|poster|wallpaper)\b|"
                    r"\b(show me (?:a|an|the) (?:image|photo|picture)|text.to.image)\b", re.IGNORECASE)


class ImageTurn(Base):
    __tablename__ = "mio_omni_image_turns"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    scope_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    job_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    source_turn: Mapped[str | None] = mapped_column(String(32), nullable=True)
    operation: Mapped[str] = mapped_column(String(12), nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)


class Intent(BaseModel):
    prompt: str = Field(min_length=2, max_length=12000)
    scope: Literal["chat", "project", "work"]
    scope_id: str | None = None
    attachment: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")


class Generate(Intent):
    mode: Literal["auto", "create", "edit"] = "auto"


def image_decision(prompt: str, *, has_previous: bool = False, attachment: bool = False) -> str:
    """Deterministic image routing; ambiguous text remains ordinary chat.

    The latest image is context, not automatic permission to edit every request.
    """
    text = prompt.strip()
    if not text:
        return "text"
    # Explicit graphic-creation intent wins even when a project or document is mentioned.
    # Contextual code, file and project edits without that intent stay with the text tools.
    if CREATE.search(text):
        return "edit" if attachment else "create"
    if TEXT_EDIT_CONTEXT.search(text) and not re.search(r"\b(photo|image|picture|portrait)\b", text, re.IGNORECASE):
        return "text"
    if attachment and EDIT.search(text):
        return "edit"
    if route_intent(text) == "image":
        return "edit" if attachment else "create"
    if has_previous and EDIT.search(text):
        return "edit"
    if has_previous and re.search(r"\b(it|this image|the image|that picture|same photo)\b", text, re.IGNORECASE) and \
            re.search(r"\b(brighter|darker|more|less|different|blue|red|green|larger|smaller)\b", text, re.IGNORECASE):
        return "edit"
    return "text"


def _check_scope(db, root: Path, scope: str, scope_id: str | None, *, create_chat: bool = False,
                 prompt: str = "") -> str | None:
    if scope == "chat":
        if scope_id is None and create_chat:
            item = Conversation(title=prompt[:140])
            db.add(item)
            db.flush()
            return item.id
        if not isinstance(scope_id, str) or not UUID.fullmatch(scope_id):
            if scope_id is None:
                return None  # New chat, before the first image or text turn.
            raise HTTPException(422, detail="Invalid chat ID")
        if db.get(Conversation, scope_id) is None:
            raise HTTPException(404, detail="Conversation not found")
        from mio.chat_lifecycle import is_archived
        if is_archived(db, scope_id) and create_chat:
            raise HTTPException(409, detail="Restore this archived chat before replying")
        return scope_id
    if scope not in ("project", "work") or not isinstance(scope_id, str) or not HEX32.fullmatch(scope_id):
        raise HTTPException(422, detail="Project or Work scope required")
    try:
        project_info(root / "work", scope_id)
    except (WorkStop, OSError) as exc:
        raise HTTPException(404, detail="Project or Work assignment unavailable") from exc
    return scope_id


def _last(db, scope: str, scope_id: str | None) -> ImageTurn | None:
    if scope_id is None:
        return None
    return db.scalars(select(ImageTurn).where(ImageTurn.scope == scope, ImageTurn.scope_id == scope_id)
                      .order_by(ImageTurn.created_at.desc(), ImageTurn.id.desc()).limit(1)).first()


def _valid_image_job(root: Path, item: ImageTurn) -> dict:
    try:
        row = _read_job(root, item.job_id)
        if row.get("backend") != "flux2" or row.get("state") not in ("queued", "running", "ready", "failed"):
            raise StudioError("Image job metadata invalid")
        return row
    except (StudioError, OSError, ValueError, FileNotFoundError):
        # A retained private image is authoritative after a runtime cleanup.
        if _asset_path(item.id).is_file():
            return {"state": "ready", "backend": "flux2", "operation": item.operation}
        return {"state": "interrupted", "backend": "flux2", "error": "Image job interrupted before persistent output"}


# The existing home directory is durable across workstation restarts. A typical
# ~/.local/share/mioagent parent is mode 0755, which is safe when owned and not
# group/world-writable. The *image leaf* must remain strictly private (0700).
RUNTIME_ROOT = Path(f"/var/tmp/mioagent-native-{os.getuid()}")
PRIVATE_IMAGE_ROOT = RUNTIME_ROOT / "studio" / "omni-images"


def _image_store() -> Path:
    """Use the same native private filesystem as MioAgent SQLite and Studio data."""
    root = PRIVATE_IMAGE_ROOT
    # Never move, delete or bulk-chmod owner image artifacts. Validate every
    # relevant directory before creating the leaf with private permissions.
    for parent in (root.parent.parent, root.parent):
        if parent.is_symlink():
            raise StudioError("Unsafe persistent image parent")
        if not parent.exists():
            try:
                parent.mkdir(mode=0o700)
            except OSError as exc:
                raise StudioError("Cannot prepare persistent image parent") from exc
        info = parent.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o022):
            raise StudioError("Persistent image parent must be owner-controlled")
    if root.is_symlink():
        raise StudioError("Unsafe persistent image folder")
    try:
        root.mkdir(mode=0o700, exist_ok=True)
        info = root.lstat()
    except OSError as exc:
        raise StudioError("Cannot prepare persistent image folder") from exc
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise StudioError("Persistent image folder must be private")
    return root

def _asset_path(turn_id: str) -> Path:
    if not HEX32.fullmatch(turn_id):
        raise StudioError("Invalid image reference")
    return _image_store() / (turn_id + ".png")


def _persist_asset(root: Path, item: ImageTurn, record: dict) -> bool:
    target = _asset_path(item.id)
    if target.exists():
        info = target.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077 or not 8 < info.st_size <= MAX_ASSET):
            raise StudioError("Stored image integrity failed")
        cached = target.read_bytes()
        if not cached.startswith(PNG) or (record.get("sha256") and
                hashlib.sha256(cached).hexdigest() != record["sha256"]):
            raise StudioError("Stored image checksum invalid")
        return True
    if record.get("state") != "ready":
        return False
    source = _jobs(root) / (item.job_id + ".png")
    if source.is_symlink() or not source.is_file():
        raise StudioError("Completed image missing")
    data = source.read_bytes()
    if (not data.startswith(PNG) or not 8 < len(data) <= MAX_ASSET
            or len(data) != record.get("bytes")
            or hashlib.sha256(data).hexdigest() != record.get("sha256")):
        raise StudioError("Image checkpoint failed integrity verification")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as writer:
            writer.write(data)
            writer.flush()
            os.fsync(writer.fileno())
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return True


def _image_status(root: Path, item: ImageTurn) -> dict:
    record = _valid_image_job(root, item)
    if record.get("state") == "ready":
        _persist_asset(root, item, record)
    return {"id": item.id, "prompt": item.prompt, "operation": item.operation,
            "source_turn": item.source_turn, "state": record.get("state"),
            "error": record.get("error"), "model": "FLUX.2 Klein 4B",
            "created_at": item.created_at.isoformat() if item.created_at else ""}


def register_omni_routes(app: FastAPI, require_token: Callable, root: Path,
                         submit: Callable[[object], Awaitable[dict]], make_request: Callable) -> None:
    auth = [Depends(require_token)]

    @app.get("/api/omni/conversations", dependencies=auth)
    def all_chats(request: Request):
        from mio.chat_lifecycle import ArchivedChat
        with request.app.state.sessions() as db:
            archived = set(db.scalars(select(ArchivedChat.conversation_id)).all())
            chats = db.scalars(select(Conversation).order_by(Conversation.updated_at.desc())).all()
            return {"conversations": [{"id": c.id, "title": c.title,
                     "updated_at": c.updated_at.isoformat(), "archived": c.id in archived}
                    for c in chats]}

    @app.post("/api/omni/intent", dependencies=auth)
    def detect(payload: Intent, request: Request):
        with request.app.state.sessions() as db:
            scope_id = _check_scope(db, root, payload.scope, payload.scope_id)
            previous = _last(db, payload.scope, scope_id)
            decision = image_decision(payload.prompt, has_previous=previous is not None,
                                      attachment=bool(payload.attachment))
            return {"operation": decision, "image": decision != "text",
                    "has_previous_image": previous is not None}

    @app.post("/api/omni/images", dependencies=auth, status_code=202)
    async def generate(payload: Generate, request: Request):
        with request.app.state.sessions() as db:
            scope_id = _check_scope(db, root, payload.scope, payload.scope_id)
            previous = _last(db, payload.scope, scope_id)
            action = (payload.mode if payload.mode != "auto" else
                      image_decision(payload.prompt, has_previous=previous is not None,
                                     attachment=bool(payload.attachment)))
            if action not in ("create", "edit"):
                raise HTTPException(422, detail="This message is not an image request")
            image_id = payload.attachment
            source_turn = None
            if action == "edit":
                if image_id is None:
                    if previous is None:
                        raise HTTPException(422, detail="Attach an image to edit first")
                    # A failed or interrupted image should not supersede the last
                    # successful reference in this exact conversation/project scope.
                    candidates = db.scalars(select(ImageTurn).where(
                        ImageTurn.scope == payload.scope, ImageTurn.scope_id == scope_id
                    ).order_by(ImageTurn.created_at.desc(), ImageTurn.id.desc()).limit(50)).all()
                    previous = next((candidate for candidate in candidates
                                     if _valid_image_job(root, candidate).get("state") == "ready"), None)
                    if previous is None:
                        raise HTTPException(409, detail="No completed image is available for editing")
                    try:
                        source = _image_status(root, previous)
                    except (StudioError, OSError) as exc:
                        raise HTTPException(409, detail="Private image storage unavailable") from exc
                    if source["state"] != "ready":
                        raise HTTPException(409, detail="Previous image is not ready for editing")
                    data = _asset_path(previous.id).read_bytes()
                    saved = save_attachment(_studio(root) / "attachments",
                                            "mio-edit-reference.png", base64.b64encode(data).decode())
                    image_id = saved["id"]
                    source_turn = previous.id
                else:
                    meta, _ = read_attachment(_studio(root) / "attachments", image_id)
                    if meta.get("kind") != "image":
                        raise HTTPException(422, detail="Editing needs a PNG or JPEG attachment")
            if action == "create" and image_id is not None:
                raise HTTPException(422, detail="A reference image requires an editing request")
            # No SD1.5 fallback: the Chat/Projects/Work image engine is FLUX.2 only.
            result = await submit(make_request(prompt=payload.prompt[:1200], backend="flux2",
                                               attachment=image_id, fallback_to_sd15=False))
            with request.app.state.sessions.begin() as db:
                resolved_id = _check_scope(db, root, payload.scope, scope_id,
                                           create_chat=True, prompt=payload.prompt)
                turn = ImageTurn(id=uuid.uuid4().hex, scope=payload.scope, scope_id=resolved_id,
                                 prompt=payload.prompt[:1200], job_id=result["id"],
                                 source_turn=source_turn, operation=action)
                db.add(turn)
                if payload.scope == "chat":
                    db.add(ChatMessage(conversation_id=resolved_id, role="user", content=payload.prompt))
                    db.add(ChatMessage(conversation_id=resolved_id, role="assistant", content=MARKER + turn.id))
                    conversation = db.get(Conversation, resolved_id)
                    conversation.updated_at = utcnow()
                db.flush()
            return {"turn_id": turn.id, "conversation_id": resolved_id,
                    "job_id": result["id"], "operation": action, "model": "FLUX.2 Klein 4B"}

    @app.get("/api/omni/turns/{scope}/{scope_id}", dependencies=auth)
    def list_turns(scope: str, scope_id: str, request: Request):
        with request.app.state.sessions() as db:
            _check_scope(db, root, scope, scope_id)
            rows = db.scalars(select(ImageTurn).where(ImageTurn.scope == scope,
                              ImageTurn.scope_id == scope_id).order_by(ImageTurn.created_at.asc(),
                              ImageTurn.id.asc())).all()
            try:
                return {"turns": [_image_status(root, item) for item in rows]}
            except (StudioError, OSError) as exc:
                raise HTTPException(409, detail="Private image storage unavailable") from exc

    @app.get("/api/omni/images/{turn_id}", dependencies=auth)
    def status(turn_id: str, request: Request):
        if not HEX32.fullmatch(turn_id):
            raise HTTPException(404, detail="Image turn unavailable")
        with request.app.state.sessions() as db:
            item = db.get(ImageTurn, turn_id)
            if item is None:
                raise HTTPException(404, detail="Image turn unavailable")
            try:
                return _image_status(root, item)
            except (StudioError, OSError) as exc:
                raise HTTPException(409, detail="Private image storage unavailable") from exc

    @app.get("/api/omni/images/{turn_id}/file", dependencies=auth)
    def asset(turn_id: str, request: Request):
        if not HEX32.fullmatch(turn_id):
            raise HTTPException(404, detail="Image unavailable")
        with request.app.state.sessions() as db:
            item = db.get(ImageTurn, turn_id)
            if item is None:
                raise HTTPException(404, detail="Image unavailable")
            try:
                record = _valid_image_job(root, item)
                if not _persist_asset(root, item, record):
                    raise HTTPException(409, detail="Image is still rendering")
                data = _asset_path(item.id).read_bytes()
            except (StudioError, OSError) as exc:
                raise HTTPException(409, detail="Private image storage unavailable") from exc
            if len(data) > MAX_ASSET or not data.startswith(PNG):
                raise HTTPException(409, detail="Stored image is invalid")
            return Response(content=data, media_type="image/png", headers={"Cache-Control": "private, no-store"})
