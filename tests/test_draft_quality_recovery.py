"""Bounded generation repair and operator-scoped fresh project recovery."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

import pytest

from mio.engineering_engine import EngineeringStop, parse_goal, parse_plan
from mio.project_mode import ProjectPolicyError
from mio.project_tasks import DRAFT_RETRIES, generate_validated_draft
from scripts.engineer_project import (
    restart_failed_goal,
    validated_restart_report,
)

PROJECT_ID = "11111111-1111-1111-1111-111111111111"


def example():
    return parse_goal(json.dumps({
        "title": "Example recovery target",
        "requirements": "Create a pure multiply(a,b) function in math_ops.py with no dependencies.",
        "criteria": ["Multiplication of 2 and 3 should give the value 6"],
        "acceptance_tests": {
            "test_math_ops.py": (
                "import unittest\nfrom math_ops import multiply\n"
                "class Check(unittest.TestCase):\n"
                "    def test_one(self):\n        self.assertEqual(multiply(2, 3), 6)\n"
            ),
        },
        "max_repairs": 1,
    }))


def plan(goal):
    return parse_plan(json.dumps({"tasks": [
        {"role": "planning", "action": "Identify Python source and tests", "criteria": []},
        {"role": "coding", "action": "Implement correct multiplication", "criteria": ["C1"]},
        {"role": "review", "action": "Verify immutable user tests", "criteria": ["C1"]},
    ]}), goal)


def report_for(goal):
    return {"goal_sha256": goal.digest, "planner_model": "gpt-oss:20b",
            "plan": plan(goal), "state": "stopped",
            "events": [
                {"event": "plan_validated", "mapped_criteria": ["C1"]},
                {"event": "project_created", "project_id": PROJECT_ID},
            ]}



@dataclass
class FakeCompletion:
    text: str
    model: str = "gpt-oss:20b"
    provider: str = "local"


class FakeRouter:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.messages = []

    async def complete(self, messages, max_tokens):
        self.messages.append((list(messages), max_tokens))
        return FakeCompletion(self.responses.pop(0))


VALID = json.dumps({"plan": ["Implement source"], "files": [
    {"path": "math_ops.py", "content": "def multiply(a, b):\n    return a * b\n"}
]})


def generate(router):
    return asyncio.run(generate_validated_draft(router, "Trusted user goal: implement multiplication"))


def test_valid_draft_one_call():
    router = FakeRouter(VALID)
    draft, result, attempts = generate(router)
    assert attempts == 1
    assert draft["files"][0]["path"] == "math_ops.py"
    assert result.provider == "local"
    assert len(router.messages) == 1


def test_invalid_empty_files_gets_one_schema_correction():
    router = FakeRouter('{"plan": ["step"], "files": []}', VALID)
    draft, _, attempts = generate(router)
    assert attempts == 2
    assert len(router.messages) == DRAFT_RETRIES
    assert "NONEMPTY" in router.messages[0][0][0]["content"]
    assert router.messages[0][1] == 3072
    assert "Include 1-3 real application file objects" in router.messages[1][0][-1]["content"]
    assert draft["file_count"] == 1


def test_two_invalid_drafts_stop_without_infinite_attempts():
    router = FakeRouter('{"plan": ["step"], "files": []}', '{"files": []}')
    with pytest.raises(ProjectPolicyError, match="after 2 attempts"):
        generate(router)
    assert len(router.messages) == 2


def test_invalid_code_syntax_gets_correction():
    bad = json.dumps({"plan": ["source"], "files": [
        {"path": "math_ops.py", "content": "def multiply(:\n"}
    ]})
    router = FakeRouter(bad, VALID)
    assert generate(router)[-1] == 2
    assert "Correct the schema and syntax" in router.messages[-1][0][-1]["content"]


def test_only_model_written_tests_do_not_count_as_application_source():
    bad = json.dumps({"plan": ["source"], "files": [
        {"path": "test_math_ops.py", "content": "import unittest\nclass T(unittest.TestCase):\n    def test_one(self):\n        self.assertTrue(True)\n"}
    ]})
    router = FakeRouter(bad, VALID)
    assert generate(router)[-1] == 2


def write_report(path, report):
    path.write_text(json.dumps(report), encoding="utf-8")
    path.chmod(0o600)


def test_original_stopped_report_and_plan_reused(tmp_path):
    goal = example()
    old = report_for(goal)
    old["events"].append({"event": "failed_draft_requeued", "project_id": PROJECT_ID})
    path = tmp_path / "original.json"
    write_report(path, old)
    found, saved_plan, project_id = validated_restart_report(path, goal)
    assert found["state"] == "stopped"
    assert saved_plan == plan(goal)
    assert project_id == PROJECT_ID


def test_restart_rejects_post_draft_progress(tmp_path):
    goal = example()
    bad = report_for(goal)
    bad["events"].append({"event": "source_applied", "project_id": PROJECT_ID})
    path = tmp_path / "original.json"
    write_report(path, bad)
    with pytest.raises(EngineeringStop, match="progressed beyond drafting"):
        validated_restart_report(path, goal)


def test_restart_rejects_modified_plan_or_goal(tmp_path):
    goal = example()
    report = report_for(goal)
    report["plan"]["tasks"][1]["criteria"] = ["C9"]
    path = tmp_path / "original.json"
    write_report(path, report)
    with pytest.raises(EngineeringStop, match="unknown criteria"):
        validated_restart_report(path, goal)
    report = report_for(goal)
    report["goal_sha256"] = "0" * 64
    write_report(path, report)
    with pytest.raises(EngineeringStop, match="eligible stopped"):
        validated_restart_report(path, goal)


def test_restart_rejects_symlink_and_insecure_report(tmp_path):
    goal = example()
    p = tmp_path / "original.json"
    write_report(p, report_for(goal))
    alias = tmp_path / "alias.json"
    alias.symlink_to(p)
    with pytest.raises(EngineeringStop, match="Missing original"):
        validated_restart_report(alias, goal)
    p.chmod(0o644)
    with pytest.raises(EngineeringStop, match="private"):
        validated_restart_report(p, goal)


class FakeAPI:
    def __init__(self, goal, planned, *, status="failed"):
        self.goal, self.planned, self.status = goal, planned, status
        self.calls = []

    def call(self, path):
        self.calls.append(path)
        if path == "status":
            return {"project_mode_enabled": True, "sandbox_verify_enabled": True}
        if path == f"projects/{PROJECT_ID}":
            return {"status": self.status, "draft": None, "title": self.goal.title,
                    "requirements": self.goal.project_requirements(self.planned),
                    "workspace": None, "apply_task_id": None}
        raise AssertionError(path)

    def create_project(self, goal, planned):
        self.calls.append("create_project")
        return {"id": "22222222-2222-2222-2222-222222222222"}


def test_restart_success_preserves_original_and_creates_new(monkeypatch):
    from scripts import engineer_project

    goal = example()
    planned = plan(goal)
    api = FakeAPI(goal, planned)
    events = []
    monkeypatch.setattr(engineer_project, "finish_goal", lambda api, goal, project_id, **kw:
                        {"project_id": project_id, "outcome": "passed"})
    result = restart_failed_goal(api, goal, planned, PROJECT_ID, record=events.append)
    assert result["project_id"] == "22222222-2222-2222-2222-222222222222"
    assert events[0]["previous_project"] == PROJECT_ID
    assert api.calls[-1] == "create_project"


def test_restart_refuses_approved_or_unrelated_project(monkeypatch):
    goal = example()
    planned = plan(goal)
    api = FakeAPI(goal, planned, status="completed")
    with pytest.raises(EngineeringStop, match="unchanged failed draft"):
        restart_failed_goal(api, goal, planned, PROJECT_ID, record=lambda _: None)
    assert "create_project" not in api.calls
