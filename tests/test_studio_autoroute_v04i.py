"""Auto tool routing intentionally cannot fake search results or images."""

import pytest

from mio.studio_autoroute import route_intent


@pytest.mark.parametrize(("prompt", "expected"), [
    ("Generate an image of a robot in a garden", "image"),
    ("Draw me a picture of a futuristic lab", "image"),
    ("Create a diagram of the robot arm", "image"),
    ("Explain how text-to-image systems work", "chat"),
    ("Draw conclusions from these results", "chat"),
    ("Draw me a robot in a space station", "image"),
    ("Generate a report comparing image generation models", "chat"),
    ("Search the web for the latest robotics papers", "research"),
    ("What is the latest version of Python?", "research"),
    ("What is the weather in Berlin today?", "research"),
    ("Find online sources about humanoid robots", "research"),
    ("Tell me a joke", "chat"),
    ("Fix this Python function", "chat"),
])
def test_intents(prompt, expected):
    assert route_intent(prompt) == expected


def test_analyze_attached_documents():
    assert route_intent("Summarize this document", ["text"]) == "analyze"
    assert route_intent("Compare these two charts", ["image", "image"]) == "analyze"


def test_explicit_modes_backward_compatible():
    assert route_intent("Generate an image", requested="chat") == "chat"
    assert route_intent("Summarize a PDF", requested="research") == "research"


def test_invalid_mode_refused():
    with pytest.raises(ValueError):
        route_intent("hello", requested="shell")


def test_automatic_studio_search_calls_real_adapter_interface(tmp_path, monkeypatch):
    """An ordinary Studio request, without mode selection, invokes research."""
    from unittest.mock import AsyncMock

    from fastapi import FastAPI, Header, HTTPException
    from fastapi.testclient import TestClient

    from mio import studio_api

    def auth(authorization: str | None = Header(default=None)):
        if authorization != "Bearer test-token":
            raise HTTPException(status_code=401)

    roles = []

    class FakeFleet:
        def __init__(self, settings, role):
            roles.append(role)

        async def complete(self, messages, max_tokens=768):
            assert "[W1]" in messages[-1]["content"]
            return type("Completion", (), {"text": "A recent report exists [W1]", "model": "mock-local"})()

    sources = [{"ref": "W1", "title": "Latest data", "url": "https://example.com/paper",
                "snippet": "Research report"}]
    lookup = AsyncMock(return_value=sources)
    monkeypatch.setattr(studio_api, "web_search", lookup)
    monkeypatch.setattr(studio_api, "FleetRouter", FakeFleet)
    app = FastAPI()
    studio_api.register_studio_routes(app, object(), auth, tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/studio/respond", headers={"Authorization": "Bearer test-token"},
                               json={"prompt": "Search the web for latest robotics research papers"})
    assert response.status_code == 200, response.text
    assert response.json()["mode"] == "research"
    assert response.json()["operation"] == "answer"
    assert response.json()["sources"] == sources
    assert roles == ["research"]
    lookup.assert_awaited_once()


def test_automatic_image_without_checkpoint_reports_real_blocker(tmp_path):
    from fastapi import FastAPI, Header, HTTPException
    from fastapi.testclient import TestClient

    from mio import studio_api

    def auth(authorization: str | None = Header(default=None)):
        if authorization != "Bearer test-token":
            raise HTTPException(status_code=401)

    app = FastAPI()
    studio_api.register_studio_routes(app, object(), auth, tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/studio/respond", headers={"Authorization": "Bearer test-token"},
                               json={"prompt": "Generate an image of a friendly robot"})
    assert response.status_code == 422
    assert "ComfyUI" in response.json()["detail"]


def test_automatic_image_with_checkpoint_dispatches_real_job(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    from fastapi import FastAPI, Header, HTTPException
    from fastapi.testclient import TestClient

    from mio import studio_api

    def auth(authorization: str | None = Header(default=None)):
        if authorization != "Bearer test-token":
            raise HTTPException(status_code=401)

    monkeypatch.setattr(studio_api, "comfy_settings", lambda root: {"checkpoint": "test.safetensors"})
    monkeypatch.setattr(studio_api, "available_checkpoints",
                        AsyncMock(return_value=["test.safetensors"]))
    completed = []

    async def fake_image(root, job_id, prompt, checkpoint):
        completed.append((prompt, checkpoint))

    monkeypatch.setattr(studio_api, "_image_task", fake_image)
    app = FastAPI()
    studio_api.register_studio_routes(app, object(), auth, tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/studio/respond", headers={"Authorization": "Bearer test-token"},
                               json={"prompt": "Create a picture of a robot"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["operation"] == "image"
    assert len(data["image_job"]) == 32
