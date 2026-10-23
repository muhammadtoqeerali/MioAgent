"""IMG3A deterministic image intent, persistence and scope safety tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from mio.database import Base, Conversation
from mio.omni_images import ImageTurn, image_decision, register_omni_routes


def test_create_intents():
    for prompt in ("Create an image of a waterfall", "Make a photorealistic photo of a person",
                   "Generate a portrait of a dog", "Draw a picture of a city"):
        assert image_decision(prompt) == "create"


def test_follow_up_edits():
    for prompt in ("Change the jacket color to red", "Make it brighter", "Remove the background",
                   "Replace the blue hat"):
        assert image_decision(prompt, has_previous=True) == "edit"
    assert image_decision("Change the project deadline", has_previous=False) == "text"


def test_text_not_hijacked():
    for prompt in ("Explain the paper", "How do I improve Python code?", "Write a research review",
                   "How many GPUs are there?", "Make a change to the software"):
        assert image_decision(prompt, has_previous=True) == "text"


def test_reference_routes_to_edit():
    assert image_decision("Change the background", attachment=True) == "edit"
    assert image_decision("Describe this photo", attachment=True) == "text"
    assert image_decision("Create an image based on this", attachment=True) == "edit"


def test_metadata_is_additive(tmp_path: Path):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    from mio.chat_lifecycle import ArchivedChat  # noqa: F401 - register the existing archived table
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory.begin() as db:
        convo = Conversation(title="A persistent image conversation")
        db.add(convo)
        db.flush()
        db.add(ImageTurn(id="a"*32, scope="chat", scope_id=convo.id,
                         prompt="Create an image of a cat", job_id="b"*32,
                         source_turn=None, operation="create"))
    with factory() as db:
        item = db.scalars(select(ImageTurn)).one()
        assert item.scope == "chat" and item.prompt.endswith("cat")
    engine.dispose()


def test_invalid_image_id_is_rejected():
    from mio.omni_images import _asset_path
    from mio.studio_files import StudioError

    with pytest.raises(StudioError):
        _asset_path("../../etc/passwd")


def test_owner_bearer_and_all_conversations(tmp_path: Path):
    db_file = tmp_path / "test.db"
    engine = create_engine("sqlite+pysqlite:///" + str(db_file), connect_args={"check_same_thread": False})
    from mio.chat_lifecycle import ArchivedChat  # noqa: F401 - register the existing archived table
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory.begin() as db:
        for i in range(103):
            db.add(Conversation(title=f"Conversation #{i}"))
    app=FastAPI()
    app.state.sessions=factory
    async def mock_submit(payload):
        return {"id":"b"*32,"state":"queued"}
    class FakePayload:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
    def require_token(authorization: str | None = __import__("fastapi").Header(default=None)):
        from fastapi import HTTPException
        if authorization != "Bearer owner-test-token":
            raise HTTPException(401, "Unauthorized")
    register_omni_routes(app, require_token, tmp_path, mock_submit, FakePayload)
    client=TestClient(app)
    assert client.get("/api/omni/conversations").status_code == 401
    response=client.get("/api/omni/conversations",headers={"Authorization":"Bearer owner-test-token"})
    assert response.status_code == 200
    assert len(response.json()["conversations"]) == 103
    assert client.post("/api/omni/images", json={"scope":"chat","prompt":"Hello world"},
                       headers={"Authorization":"Bearer owner-test-token"}).status_code == 422
    engine.dispose()


def test_job_requires_explicit_image_request():
    assert image_decision("What's on your mind?") == "text"
    assert image_decision("Please explain this chart", has_previous=True) == "text"


def test_reference_cannot_be_mistaken_for_new_generation():
    assert image_decision("create an image of that mountain", attachment=True) == "edit"


def test_schema_has_no_destructive_cascade():
    assert ImageTurn.__tablename__ == "mio_omni_image_turns"
    assert "scope_id" in ImageTurn.__table__.columns


def test_software_edits_do_not_route_to_old_image():
    for prompt in ("Edit the Python file", "Change the dashboard button color",
                   "Remove the repository file", "Modify the TypeScript component"):
        assert image_decision(prompt, has_previous=True) == "text"


def test_graphic_creation_for_projects_still_routes_to_flux():
    for prompt in ("Design a logo for my project", "Draw a picture for the report",
                   "Make a portrait for my document"):
        assert image_decision(prompt, has_previous=True) == "create"


def test_scope_does_not_change_text_intent():
    assert image_decision("Write a code review", has_previous=True) == "text"
    assert image_decision("Remove background", has_previous=True) == "edit"
    assert image_decision("Create a new image", has_previous=True) == "create"
