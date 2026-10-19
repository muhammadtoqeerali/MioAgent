"""Goal-driven engineering controller: policy, immutable acceptance and bounded APIs."""

import hashlib
import json

import pytest

from mio.engineering_engine import (
    EngineeringStop,
    lock_acceptance_tests,
    parse_goal,
    parse_plan,
    validate_review_draft,
)
from scripts.engineer_project import execute_goal, wait_project

PARENT = "11111111-1111-1111-1111-111111111111"
TEST_CODE = (
    "import unittest\n"
    "from math_ops import multiply\n\n"
    "class TestMath(unittest.TestCase):\n"
    "    def test_two(self):\n        self.assertEqual(multiply(2, 3), 6)\n"
    "    def test_three(self):\n        self.assertEqual(multiply(3, 4), 12)\n"
    "    def test_four(self):\n        self.assertEqual(multiply(5, 5), 25)\n"
)


def payload(**overrides):
    result = {
        "title": "Verified multiplication agent", "requirements":
            "Implement pure integer multiplication in math_ops.py using no external packages.",
        "criteria": [
            "multiply(2, 3) must return 6",
            "multiply(3, 4) must return 12",
            "multiply(5, 5) must return 25",
        ],
        "acceptance_tests": {"test_math_ops.py": TEST_CODE}, "max_repairs": 2,
    }
    return json.dumps(result | overrides)


def file(path, content):
    return {"path": path, "content": content,
            "bytes": len(content.encode()),
            "sha256": hashlib.sha256(content.encode()).hexdigest()}


def review(tests=TEST_CODE, *, status="review", extra=None):
    files = [file("math_ops.py", "def multiply(a, b):\n    return a * b\n"),
             file("test_math_ops.py", tests)]
    if extra is not None:
        files.append(extra)
    return {"id": PARENT, "status": status, "draft": {"files": files}}


def plan_json(criteria=("C1", "C2", "C3")):
    return json.dumps({"tasks": [
        {"role": "planning", "action": "Read and decompose user criteria", "criteria": []},
        {"role": "coding", "action": "Implement multiplication source and call sites", "criteria": list(criteria)},
        {"role": "review", "action": "Verify all acceptance tests unchanged", "criteria": list(criteria)},
    ]})


def test_goal_accepts_meaningful_independent_cases():
    goal = parse_goal(payload())
    assert goal.max_repairs == 2
    assert goal.project_requirements().count("FILE test_math_ops.py") == 2
    assert len(goal.digest) == 64


@pytest.mark.parametrize("bad", [
    {"max_repairs": 0}, {"max_repairs": 3}, {"max_repairs": True},
    {"acceptance_tests": {}},
    {"acceptance_tests": {"../test_math_ops.py": TEST_CODE}},
    {"acceptance_tests": {"source.py": TEST_CODE}},
    {"criteria": ["short"]},
    {"acceptance_tests": {"test_math_ops.py": "def test_empty():\n    pass\n"}},
    {"criteria": ["multiply(2, 3) must return 6", "multiply(3, 4) must return 12",
                  "multiply(5, 5) must return 25", "extra criterion that has no test" ]},
])
def test_bad_goal_rejected(bad):
    with pytest.raises(EngineeringStop):
        parse_goal(payload(**bad))


def test_malformed_json_and_unknown_schema_stopped():
    with pytest.raises(EngineeringStop):
        parse_goal('{"wrong": 1}')
    with pytest.raises(EngineeringStop):
        parse_goal('not a JSON object')


def test_goal_rejects_large_prompt():
    with pytest.raises(EngineeringStop, match="Requirements"):
        parse_goal(payload(requirements="meaningful goals " * 165))


def test_plan_links_all_criteria_and_real_local_model():
    plan = parse_plan(plan_json(), parse_goal(payload()))
    assert plan["criteria_mapped"] == ["C1", "C2", "C3"]
    assert [t["role"] for t in plan["tasks"]] == ["planning", "coding", "review"]
    assert all(t["model"] == "gpt-oss:20b" for t in plan["tasks"])
    assert all(t["skills"] == [] and t["tool_execution"] is False for t in plan["tasks"])


def test_plan_missing_criterion_stopped():
    with pytest.raises(EngineeringStop, match="mapping"):
        parse_plan(plan_json(("C1", "C2")), parse_goal(payload()))


def test_unknown_plan_role_stopped():
    bad = plan_json().replace('"role": "coding"', '"role": "shell"')
    with pytest.raises(EngineeringStop, match="role"):
        parse_plan(bad, parse_goal(payload()))


def test_plan_rejects_unstructured_model_output():
    with pytest.raises(EngineeringStop, match="JSON"):
        parse_plan("You should run a few tests", parse_goal(payload()))


def test_valid_draft_has_original_test_hashes():
    expected = parse_goal(payload())
    evidence = validate_review_draft(review(), expected)
    assert evidence["test_cases"] == 3
    assert evidence["source_files"] == ["math_ops.py"]
    assert evidence["test_sha256"]["test_math_ops.py"] == hashlib.sha256(TEST_CODE.encode()).hexdigest()


def test_different_generated_tests_cannot_be_approved():
    with pytest.raises(EngineeringStop, match="differ"):
        validate_review_draft(review(TEST_CODE + "\n# changed by model"), parse_goal(payload()))


def test_added_model_test_is_rejected():
    with pytest.raises(EngineeringStop, match="differ"):
        validate_review_draft(review(extra=file("test_fake.py", "def test_ok(): assert True")), parse_goal(payload()))


def test_non_python_model_code_rejected():
    with pytest.raises(EngineeringStop, match="source and safe"):
        validate_review_draft(review(extra=file("command.sh", "echo hello")), parse_goal(payload()))


def test_hash_tampering_rejected():
    value = review()
    value["draft"]["files"][0]["sha256"] = "0" * 64
    with pytest.raises(EngineeringStop, match="hash"):
        validate_review_draft(value, parse_goal(payload()))


def test_unsafe_source_path_rejected():
    with pytest.raises(EngineeringStop, match="Unsafe"):
        validate_review_draft(review(extra=file("../more.py", "x=1")), parse_goal(payload()))


def test_draft_only_approved_at_review_state():
    with pytest.raises(EngineeringStop, match="review-stage"):
        validate_review_draft(review(status="completed"), parse_goal(payload()))


class FakeAgentAPI:
    def __init__(self, *, drift=False, on=True):
        self.events = []
        self.stage = "drafting"
        self.drift = drift
        self.on = on

    def create_project(self, goal, plan):
        assert "Reviewed local engineering plan" in goal.project_requirements(plan)
        self.events.append(("create", True))
        return {"id": PARENT, "status": "drafting"}

    def lock_tests(self, project_id, goal):
        self.events.append((f"projects/{project_id}/acceptance", True))
        return review(TEST_CODE + "# change" if self.drift else TEST_CODE, status="review")

    def call(self, path, *, post=False):
        self.events.append((path, post))
        if path == "status":
            return {"project_mode_enabled": self.on, "sandbox_verify_enabled": self.on}
        if path == f"projects/{PARENT}/apply" and post:
            self.stage = "applying"
            return {"status": "applying"}
        if path == f"projects/{PARENT}":
            if self.stage == "drafting":
                self.stage = "review"
            elif self.stage == "applying":
                self.stage = "completed"
            return review(TEST_CODE if self.stage == "completed" else "def test_fake():\n    assert True\n", status=self.stage)
        raise AssertionError(f"Unexpected API operation: {path} {post}")


def test_full_controller_verifies_before_delegation():
    api = FakeAgentAPI()
    messages = []
    def verified_runner(client, pid, *, attempts, report):
        assert client is api and pid == PARENT and attempts == 2
        report({"history": [{"attempt": 0}], "current_project": pid})
        return {"outcome": "passed", "project_id": pid, "attempts": 0,
                "history": [{"outcome": "passed", "tests_run": 3}]}
    result = execute_goal(api, parse_goal(payload()), parse_plan(plan_json(), parse_goal(payload())),
                          record=messages.append, repair_runner=verified_runner)
    assert result["outcome"] == "passed"
    assert result["test_cases"] == 3
    assert [e["event"] for e in messages] == [
        "plan_validated", "project_created", "user_acceptance_tests_verified",
        "source_applied", "repair_progress", "run_finished"]
    assert (f"projects/{PARENT}/apply", True) in api.events


def test_model_cannot_modify_acceptance_and_get_approved():
    api = FakeAgentAPI(drift=True)
    with pytest.raises(EngineeringStop, match="differ"):
        execute_goal(api, parse_goal(payload()), parse_plan(plan_json(), parse_goal(payload())),
                     record=lambda e: None, repair_runner=lambda *a, **kw: pytest.fail("Never run"))
    assert not any(path.endswith("/apply") for path, _ in api.events if isinstance(path, str))


def test_disabled_sandbox_blocks_project_creation():
    api = FakeAgentAPI(on=False)
    with pytest.raises(EngineeringStop, match="enabled"):
        execute_goal(api, parse_goal(payload()), parse_plan(plan_json(), parse_goal(payload())),
                     record=lambda e: None)
    assert not any(path == "create" for path, _ in api.events)


def test_wait_project_bad_state_stop_no_loop():
    class Unavailable:
        def call(self, path):
            return {"status": "failed", "error": "bad model response"}
    with pytest.raises(EngineeringStop, match="bad model response"):
        wait_project(Unavailable(), PARENT, "review", pause=lambda s: None)


def test_api_lock_replaces_weak_model_test_but_keeps_source_bytes():
    model_draft = review(tests="def test_fake():\n    assert True\n")["draft"]
    model_draft["plan"] = ["Implement multiplication"]
    checked = lock_acceptance_tests(model_draft, {"test_math_ops.py": TEST_CODE})
    assert checked["file_count"] == 2
    assert checked["files"][0]["sha256"] == model_draft["files"][0]["sha256"]
    assert checked["files"][1]["content"] == TEST_CODE


def test_api_lock_rejects_test_without_assertions():
    model_draft = review()["draft"] | {"plan": ["Implement multiplication"]}
    with pytest.raises(EngineeringStop, match="meaningful"):
        lock_acceptance_tests(model_draft, {"test_math_ops.py": "def test_empty():\n    pass  # no real assertion here\n"})


def test_api_lock_rejects_non_source_project():
    model_draft = {"plan": ["nothing"], "files": [file("test_fake.py", TEST_CODE)]}
    with pytest.raises(EngineeringStop, match="no application"):
        lock_acceptance_tests(model_draft, {"test_math_ops.py": TEST_CODE})


def test_real_authenticated_api_locks_tests_only_before_approval(tmp_path):
    from fastapi.testclient import TestClient

    from mio.api import create_app
    from mio.config import Settings
    from mio.database import Project
    from mio.project_mode import validate_draft

    database_url = f"sqlite+pysqlite:///{tmp_path / 'agent.db'}"
    config = Settings(
        _env_file=None, mio_api_token="T" * 40, mio_database_url=database_url,
        mio_local_model="gpt-oss:20b", mio_enable_project_mode=True,
        mio_enable_sandbox_verify=True,
    )
    app = create_app(config)
    model_draft = validate_draft(json.dumps({"plan": ["Do the work"], "files": [
        {"path": "math_ops.py", "content": "def multiply(a, b):\n    return a*b\n"},
        {"path": "test_fake.py", "content": "def test_fake():\n    assert True\n"},
    ]}))
    headers = {"Authorization": "Bearer " + "T" * 40}
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        with app.state.sessions.begin() as db:
            project = Project(title="Sample", requirements="Make a very small source project",
                              status="review", draft_json=json.dumps(model_draft))
            db.add(project)
            db.flush()
            project_id = project.id
        url = f"/api/projects/{project_id}/acceptance"
        assert client.post(url, json={"approved": True, "tests": dict(
            parse_goal(payload()).acceptance_tests)}).status_code == 401
        reply = client.post(url, json={"approved": True, "tests": {
            "test_math_ops.py": TEST_CODE}}, headers=headers)
        assert reply.status_code == 200, reply.text
        data = reply.json()
        assert data["status"] == "review"
        evidence = validate_review_draft(data, parse_goal(payload()))
        assert evidence["test_cases"] == 3
        assert "test_fake.py" not in [f["path"] for f in data["draft"]["files"]]
        # Server stores the trusted tests in SQLite before any source approval.
        with app.state.sessions.begin() as db:
            stored = db.get(Project, project_id)
            assert json.loads(stored.draft_json)["files"][1]["content"] == TEST_CODE
            stored.status = "completed"
        rejected = client.post(url, json={"approved": True, "tests": {
            "test_math_ops.py": TEST_CODE}}, headers=headers)
        assert rejected.status_code == 409


def test_documented_goal_example_is_policy_valid():
    from pathlib import Path

    contract = Path(__file__).resolve().parents[1] / "docs/examples/v04a_multiply_goal.json"
    goal = parse_goal(contract.read_bytes())
    assert len(goal.criteria) == 3
    assert len(goal.acceptance_tests) == 1
