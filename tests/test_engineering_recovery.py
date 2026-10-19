"""v0.4B bounded local-model diagnostics and same-project draft recovery."""

import asyncio
import json
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from mio.api import create_app
from mio.config import Settings
from mio.database import Project, Task
from mio.engineering_engine import EngineeringStop, parse_goal, parse_plan
from mio.llm import ModelRouter, ModelUnavailable
from scripts.engineer_project import resume_goal, validated_resume_report

PROJECT_ID = "11111111-1111-1111-1111-111111111111"
TEST_CODE = (
    "import unittest\nfrom math_ops import multiply\n"
    "class Check(unittest.TestCase):\n"
    "    def test_one(self):\n        self.assertEqual(multiply(2, 3), 6)\n"
)


def example():
    return parse_goal(json.dumps({
        "title": "Example recovery target",
        "requirements": "Create a pure multiply(a,b) function in math_ops.py with no dependencies.",
        "criteria": ["Multiplication of 2 and 3 should give the value 6"],
        "acceptance_tests": {"test_math_ops.py": TEST_CODE},
        "max_repairs": 1,
    }))


def plan(goal):
    raw = {"tasks": [
        {"role": "planning", "action": "Identify Python source and tests", "criteria": []},
        {"role": "coding", "action": "Implement correct multiplication", "criteria": ["C1"]},
        {"role": "review", "action": "Verify immutable user tests", "criteria": ["C1"]},
    ]}
    return parse_plan(json.dumps(raw), goal)


def report_for(goal):
    return {"goal_sha256": goal.digest, "planner_model": "gpt-oss:20b",
            "plan": plan(goal), "state": "stopped",
            "events": [
                {"event": "plan_validated", "mapped_criteria": ["C1"]},
                {"event": "project_created", "project_id": PROJECT_ID},
            ]}


def test_report_resume_no_replanning_or_goals_tampered(tmp_path):
    goal = example()
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report_for(goal)))
    path.chmod(0o600)
    loaded, planned, pid = validated_resume_report(path, goal)
    assert pid == PROJECT_ID
    assert planned == plan(goal)
    assert loaded["state"] == "stopped"
    invalid = report_for(goal)
    invalid["events"].append({"event": "source_applied"})
    path.write_text(json.dumps(invalid))
    with pytest.raises(EngineeringStop, match="manual review"):
        validated_resume_report(path, goal)


def test_report_must_be_private_exact_digest_and_stopped(tmp_path):
    goal = example()
    path = tmp_path / "report.json"
    data = report_for(goal)
    path.write_text(json.dumps(data))
    path.chmod(0o644)
    with pytest.raises(EngineeringStop, match="private"):
        validated_resume_report(path, goal)
    path.chmod(0o600)
    data["goal_sha256"] = "0" * 64
    path.write_text(json.dumps(data))
    with pytest.raises(EngineeringStop, match="matching"):
        validated_resume_report(path, goal)
    data["goal_sha256"] = goal.digest
    data["state"] = "finished"
    path.write_text(json.dumps(data))
    with pytest.raises(EngineeringStop, match="matching"):
        validated_resume_report(path, goal)


async def sleeping_worker(*args, **kwargs):
    await asyncio.Event().wait()


def test_real_api_authorized_once_only_draft_recovery(tmp_path):
    settings = Settings(
        _env_file=None, mio_api_token="X" * 40,
        mio_database_url=f"sqlite+pysqlite:///{tmp_path / 'db.sqlite'}",
        mio_local_model="gpt-oss:20b", mio_enable_project_mode=True,
        mio_enable_sandbox_verify=True, mio_poll_seconds=60,
    )
    headers = {"Authorization": f"Bearer {'X' * 40}"}
    with patch("mio.api.worker_loop", sleeping_worker):
        app = create_app(settings)
        with TestClient(app) as client:
            goal = example()
            with app.state.sessions.begin() as db:
                project = Project(id=PROJECT_ID, title=goal.title,
                                  requirements=goal.project_requirements(plan(goal)),
                                  status="failed", error="local model unavailable (HTTPStatusError)")
                failed = Task(kind="project_draft", prompt=PROJECT_ID, status="failed",
                              error="local model unavailable (HTTPStatusError)")
                db.add_all([project, failed])
                db.flush()
                project.draft_task_id = failed.id
                previous_id = failed.id
            url = f"/api/projects/{PROJECT_ID}/retry-draft"
            assert client.post(url, json={"approved": True}).status_code == 401
            assert client.post(url, json={"approved": False}, headers=headers).status_code == 422
            result = client.post(url, json={"approved": True}, headers=headers)
            assert result.status_code == 202, result.text
            value = result.json()
            assert value["status"] == "drafting"
            assert value["id"] == PROJECT_ID
            assert value["draft_task_id"] != previous_id
            assert value["error"] is None
            assert client.post(url, json={"approved": True}, headers=headers).status_code == 409
            with app.state.sessions() as db:
                tasks = db.query(Task).filter(Task.prompt == PROJECT_ID).all()
                assert len(tasks) == 2
                assert sorted(t.status for t in tasks) == ["failed", "queued"]


def test_real_api_does_not_retry_non_model_errors_or_written_projects(tmp_path):
    settings = Settings(
        _env_file=None, mio_api_token="X" * 40,
        mio_database_url=f"sqlite+pysqlite:///{tmp_path / 'db.sqlite'}",
        mio_local_model="gpt-oss:20b", mio_enable_project_mode=True,
        mio_enable_sandbox_verify=True,
    )
    headers = {"Authorization": f"Bearer {'X' * 40}"}
    with patch("mio.api.worker_loop", sleeping_worker):
        app = create_app(settings)
        with TestClient(app) as client:
            with app.state.sessions.begin() as db:
                project = Project(id=PROJECT_ID, title="Bad project",
                                  requirements="A project that failed a static safety gate",
                                  status="failed", error="Policy rejects unsafe file")
                failed = Task(kind="project_draft", prompt=PROJECT_ID, status="failed")
                db.add_all([project, failed])
                db.flush()
                project.draft_task_id = failed.id
            url = f"/api/projects/{PROJECT_ID}/retry-draft"
            assert client.post(url, json={"approved": True}, headers=headers).status_code == 409
            with app.state.sessions.begin() as db:
                project = db.get(Project, PROJECT_ID)
                project.error = "local model HTTP 500"
                project.draft_json = "{}"
            assert client.post(url, json={"approved": True}, headers=headers).status_code == 409


def test_resume_rejects_mismatched_project_without_retry():
    goal = example()
    class API:
        def __init__(self):
            self.calls = []
        def call(self, path, post=False):
            self.calls.append(path)
            if path == "status":
                return {"project_mode_enabled": True, "sandbox_verify_enabled": True}
            return {"title": goal.title, "requirements": "different requirements",
                    "status": "failed", "draft": None, "workspace": None,
                    "apply_task_id": None, "error": "local model HTTP 500"}
        def retry_failed_draft(self, project_id):
            pytest.fail("A mismatched project must never be requeued")
    with pytest.raises(EngineeringStop, match="does not match"):
        resume_goal(API(), goal, plan(goal), PROJECT_ID, record=lambda e: None)


def test_http_failure_exposes_status_not_prompt_or_body(monkeypatch):
    sensitive = "a-very-private-secret-prompt"
    def reply(request):
        assert sensitive in request.content.decode()
        return httpx.Response(500, json={"error": sensitive}, request=request)
    client = httpx.AsyncClient
    def mock_client(*args, **kwargs):
        return client(*args, transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(httpx, "AsyncClient", mock_client)
    settings = Settings(_env_file=None, mio_api_token="X" * 40,
                        mio_local_model="gpt-oss:20b", mio_model_route="local")
    with pytest.raises(ModelUnavailable) as exc:
        asyncio.run(ModelRouter(settings).complete([{"role": "user", "content": sensitive}]))
    error = str(exc.value)
    assert "HTTP 500" in error
    assert sensitive not in error


def test_successful_draft_uses_extended_inference_timeout(monkeypatch):
    timeouts = []
    client = httpx.AsyncClient
    def mock_client(*args, **kwargs):
        timeouts.append(kwargs["timeout"].read)
        return client(*args, transport=httpx.MockTransport(lambda r: httpx.Response(
            200, json={"choices": [{"message": {"content": "OK"}}]}, request=r,
        )), **kwargs)
    monkeypatch.setattr(httpx, "AsyncClient", mock_client)
    settings = Settings(_env_file=None, mio_api_token="X" * 40,
                        mio_local_model="gpt-oss:20b", mio_model_route="local")
    output = asyncio.run(ModelRouter(settings).complete([{"role": "user", "content": "test"}],
                                                         max_tokens=2048))
    assert output.text == "OK"
    assert timeouts == [240.0]


def test_successful_resume_continues_same_project_and_original_tests():
    import hashlib

    goal = example()
    planned = plan(goal)
    events = []

    class API:
        def __init__(self):
            self.status = "failed"
            self.retry_calls = 0

        def call(self, path, post=False):
            if path == "status":
                return {"project_mode_enabled": True, "sandbox_verify_enabled": True}
            if path == f"projects/{PROJECT_ID}":
                if self.status == "drafting":
                    self.status = "review"
                elif self.status == "applying":
                    self.status = "completed"
                result = {"id": PROJECT_ID, "title": goal.title,
                          "requirements": goal.project_requirements(planned),
                          "status": self.status, "workspace": None, "apply_task_id": None,
                          "error": "local model HTTP 500" if self.status == "failed" else None,
                          "draft": None}
                if self.status == "completed":
                    result["draft"] = {"files": [{"path": "test_math_ops.py",
                        "content": TEST_CODE,
                        "sha256": hashlib.sha256(TEST_CODE.encode()).hexdigest()}]}
                return result
            if path == f"projects/{PROJECT_ID}/apply" and post:
                self.status = "applying"
                return {"status": "applying"}
            raise AssertionError((path, post))

        def retry_failed_draft(self, project_id):
            assert project_id == PROJECT_ID
            self.retry_calls += 1
            self.status = "drafting"
            return {"id": PROJECT_ID, "status": "drafting"}

        def lock_tests(self, project_id, received_goal):
            assert self.status == "review"
            assert project_id == PROJECT_ID and received_goal == goal
            return {"id": PROJECT_ID, "status": "review",
                    "draft": {"files": [
                        {"path": "math_ops.py", "content": "def multiply(a,b): return a*b\n",
                         "sha256": hashlib.sha256(b"def multiply(a,b): return a*b\n").hexdigest()},
                        {"path": "test_math_ops.py", "content": TEST_CODE,
                         "sha256": hashlib.sha256(TEST_CODE.encode()).hexdigest()},
                    ]}}

    api = API()
    def verified_runner(client, pid, *, attempts, report):
        assert client is api and pid == PROJECT_ID and attempts == 1
        return {"outcome": "passed", "project_id": PROJECT_ID,
                "attempts": 0, "history": [{"outcome": "passed", "tests_run": 1}]}

    result = resume_goal(api, goal, planned, PROJECT_ID, record=events.append,
                         repair_runner=verified_runner)
    assert result["outcome"] == "passed"
    assert api.retry_calls == 1
    assert events[0] == {"event": "failed_draft_requeued", "project_id": PROJECT_ID}
    assert events[-1]["event"] == "run_finished"
