"""Repair prompts and proposals are bounded; tests and approved files remain immutable."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from mio.api import create_app
from mio.config import Settings
from mio.database import Project, Task, create_database
from mio.llm import Completion
from mio.project_mode import ProjectPolicyError, apply_draft, validate_draft
from mio.repair_proposal import repair_messages, validate_repair_reply

PID = "00000000-0000-4000-8000-000000000001"
DRAFT = validate_draft(json.dumps({
    "plan": ["Implement calculator", "Test functions"],
    "files": [
        {"path": "calculator.py", "content": "def add(a, b):\n    return a - b\n"},
        {"path": "test_calculator.py", "content": (
            "import unittest\nfrom calculator import add\n"
            "class T(unittest.TestCase):\n    def test_add(self):\n"
            "        self.assertEqual(add(1, 2), 3)\n"
        )},
        {"path": "README.md", "content": "Small calculator.\n"},
    ],
}))
FAILURE = {"outcome": "failed", "passed": False, "tests_run": 1,
           "executed": True, "log": "test_add: AssertionError: -1 != 3"}
REPLY = json.dumps({"diagnosis": "add subtracts instead of adding", "files": [
    {"path": "calculator.py", "content": "def add(a, b):\n    return a + b\n"}
]})


def test_valid_repair_keeps_original_tests_byte_identical():
    proposal = validate_repair_reply(REPLY, DRAFT)
    assert proposal["changed_files"] == ["calculator.py"]
    assert proposal["candidate"]["files"][1]["sha256"] == DRAFT["files"][1]["sha256"]
    assert DRAFT["files"][0]["content"] == "def add(a, b):\n    return a - b\n"
    assert proposal["executed"] is False


@pytest.mark.parametrize("path", ["test_calculator.py", "other.py", "../calculator.py", "README.md"])
def test_repair_rejects_test_edits_and_new_paths(path):
    response = json.dumps({"diagnosis": "bad", "files": [{"path": path, "content": "pass\n"}]})
    with pytest.raises(ProjectPolicyError):
        validate_repair_reply(response, DRAFT)


def test_repair_rejects_noop_and_syntax_failure():
    for content in (DRAFT["files"][0]["content"], "def bad(\n"):
        with pytest.raises(ProjectPolicyError):
            validate_repair_reply(json.dumps({"diagnosis": "fix", "files": [
                {"path": "calculator.py", "content": content}]}), DRAFT)


def test_repair_requires_real_failed_execution_and_bounded_context():
    msg = repair_messages("Fix calculator", DRAFT, FAILURE)
    assert "sandbox_failure_log" in msg[1]["content"]
    with pytest.raises(ProjectPolicyError):
        repair_messages("Fix calculator", DRAFT, {**FAILURE, "passed": True})
    with pytest.raises(ProjectPolicyError):
        repair_messages("Fix calculator", DRAFT, {**FAILURE, "executed": False})


def fixture_app(tmp_path, monkeypatch, *, valid_failure=True):
    from mio import project_mode as pm
    monkeypatch.setattr(pm, "_mount_type", lambda _: "ext4")
    root = tmp_path / "artifacts"
    apply_draft(root, PID, DRAFT, require_native=False)
    settings = Settings(mio_api_token="Q" * 48,
                        mio_database_url=f"sqlite+pysqlite:///{tmp_path / 'db.sqlite'}",
                        mio_workspace_root=tmp_path, mio_project_root=root,
                        mio_enable_project_mode=True, mio_enable_sandbox_verify=True,
                        mio_local_model="test-model", mio_poll_seconds=0.1)
    engine, sessions = create_database(settings.mio_database_url)
    with sessions.begin() as db:
        db.add(Project(id=PID, title="Calculator", requirements="Build a calculator with add",
                       status="completed", workspace_path=str(root / PID),
                       draft_json=json.dumps(DRAFT)))
        verify_task = Task(kind="project_verify", prompt=PID, status="completed",
                           result_json=json.dumps(FAILURE if valid_failure else {
                               **FAILURE, "passed": True, "outcome": "passed"}))
        db.add(verify_task)
    engine.dispose()
    return settings, root


def test_api_rejects_unverified_repair_and_anonymous_calls(tmp_path, monkeypatch):
    settings, _ = fixture_app(tmp_path, monkeypatch, valid_failure=False)
    headers = {"Authorization": f"Bearer {settings.mio_api_token}"}
    with TestClient(create_app(settings)) as client:
        route = f"/api/projects/{PID}/repair"
        assert client.post(route, json={"approved": True}).status_code == 401
        assert client.post(route, headers=headers, json={"approved": True}).status_code == 409
        assert client.get(route, headers=headers).json()["status"] == "not_run"


def test_api_local_model_proposal_promotes_immutable_child(tmp_path, monkeypatch):
    from mio import llm

    settings, root = fixture_app(tmp_path, monkeypatch)

    async def fake_complete(self, messages, max_tokens=768):
        assert self.settings.mio_allow_cloud is False
        assert self.settings.mio_model_route == "local"
        assert "test_calculator.py" in messages[1]["content"] or "calculator.py" in messages[1]["content"]
        return Completion(text=REPLY, provider="local", model="test-model")

    monkeypatch.setattr(llm.ModelRouter, "complete", fake_complete)
    headers = {"Authorization": f"Bearer {settings.mio_api_token}"}
    route = f"/api/projects/{PID}/repair"
    with TestClient(create_app(settings)) as client:
        assert client.post(route, headers=headers, json={"approved": False}).status_code == 422
        queued = client.post(route, headers=headers, json={"approved": True})
        assert queued.status_code == 202, queued.text
        assert client.post(route, headers=headers, json={"approved": True}).status_code == 409
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            state = client.get(route, headers=headers).json()
            if state["status"] in {"completed", "failed"}:
                break
            time.sleep(0.05)
        assert state["status"] == "completed", state
        assert state["result"]["changed_files"] == ["calculator.py"]
        assert (root / PID / "calculator.py").read_text() == "def add(a, b):\n    return a - b\n"
        promoted = client.post(route + "/use", headers=headers, json={"approved": True})
        assert promoted.status_code == 201, promoted.text
        candidate = promoted.json()
        assert candidate["status"] == "review"
        assert candidate["id"] != PID
        assert candidate["draft"]["files"][0]["content"] == "def add(a, b):\n    return a + b\n"
        assert candidate["draft"]["files"][1]["sha256"] == DRAFT["files"][1]["sha256"]
        assert client.post(route + "/use", headers=headers, json={"approved": True}).status_code == 409
        assert (root / candidate["id"]).exists() is False
        assert (root / PID / "calculator.py").read_text() == "def add(a, b):\n    return a - b\n"
