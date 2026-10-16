"""Phase 2 regression tests without network, GPU, cloud billing, or real model downloads."""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from mio.api import create_app
from mio.config import Settings
from mio.llm import Completion, ModelRouter, ModelUnavailable, validate_provider_url
from mio.supervisor import bounded_messages, parse_plan


@pytest.fixture
def ai_settings(tmp_path):
    return Settings(
        mio_api_token="z" * 48,
        mio_database_url=f"sqlite+pysqlite:///{tmp_path / 'ai.db'}",
        mio_workspace_root=tmp_path,
        mio_local_model="test-local-model",
        mio_poll_seconds=0.1,
    )


def test_url_safety_and_cloud_off(ai_settings):
    assert validate_provider_url("http://127.0.0.1:11434/v1", local=True)
    for bad in ("http://example.com/v1", "http://192.168.1.10/v1", "file:///etc/passwd"):
        with pytest.raises(ValueError):
            validate_provider_url(bad, local=True)
    with pytest.raises(ValueError):
        validate_provider_url("http://api.example.com/v1", local=False)
    assert [p[0] for p in ModelRouter(ai_settings).providers()] == ["local"]


def test_budget_and_planner_parsing():
    assert parse_plan('{"steps":["One","Two"]}') == ["One", "Two"]
    assert len(parse_plan("invalid")) == 2
    context = bounded_messages([{"role": "user", "content": "x" * 10000}], [], max_chars=100)
    assert context == []


def test_no_model_rejected(tmp_path):
    settings = Settings(mio_api_token="a" * 48, mio_database_url=f"sqlite+pysqlite:///{tmp_path/'no.db'}")
    with TestClient(create_app(settings)) as client:
        headers = {"Authorization": "Bearer " + settings.mio_api_token}
        assert client.post("/api/assistant/ask", headers=headers, json={"prompt": "Hello"}).status_code == 409
        assert client.get("/api/assistant/status").status_code == 401


def test_persistent_conversation_and_memory(ai_settings, monkeypatch):
    async def fake_complete(self, messages, max_tokens=768):
        if "task planner" in messages[0]["content"]:
            return Completion('{"steps":["Read context","Write answer"]}', "local", "mock", 8, 7)
        return Completion("This is a REAL mock response used only in unit tests.",
                          "local", "mock", 14, 9)

    monkeypatch.setattr(ModelRouter, "complete", fake_complete)
    headers = {"Authorization": "Bearer " + ai_settings.mio_api_token}
    with TestClient(create_app(ai_settings)) as client:
        response = client.post("/api/assistant/memories", headers=headers,
                               json={"content": "MioAgent is an AI workstation project."})
        assert response.status_code == 201
        memory_id = response.json()["id"]
        job = client.post("/api/assistant/ask", headers=headers,
                          json={"prompt": "Explain the MioAgent project"})
        assert job.status_code == 202, job.text
        run_id, conv_id = job.json()["task_id"], job.json()["conversation_id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            task = client.get(f"/api/tasks/{run_id}", headers=headers).json()
            if task["status"] in {"completed", "failed"}:
                break
            time.sleep(0.05)
        assert task["status"] == "completed", task
        assert task["progress"] == 100
        assert task["result"]["plan"] == ["Read context", "Write answer"]
        messages = client.get(f"/api/assistant/conversations/{conv_id}", headers=headers).json()
        assert [m["role"] for m in messages["messages"]] == ["user", "assistant"]
        assert len(client.get("/api/assistant/conversations", headers=headers).json()["conversations"]) == 1
        assert client.delete(f"/api/assistant/memories/{memory_id}", headers=headers).status_code == 200
        assert client.get("/api/assistant/memories", headers=headers).json()["memories"] == []
    # Confirm task results and messages survive an API process restart.
    with TestClient(create_app(ai_settings)) as client:
        messages = client.get(f"/api/assistant/conversations/{conv_id}", headers=headers).json()
        assert len(messages["messages"]) == 2
        assert client.get(f"/api/tasks/{run_id}", headers=headers).json()["status"] == "completed"


def test_router_handles_unavailable_models_without_secret(ai_settings):
    router = ModelRouter(ai_settings.model_copy(update={
        "mio_local_base_url": "http://127.0.0.1:1/v1"
    }))
    with pytest.raises(ModelUnavailable):
        asyncio.run(router.complete([{"role": "user", "content": "Test"}]))
