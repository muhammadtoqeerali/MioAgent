"""v0.3D bounded-runner policy tests; no GPU or network dependencies."""

import hashlib

import pytest

from scripts.autonomous_repair import RunStopped, run_cycle, verify_source_policy
from scripts.autonomous_repair import test_fingerprints as fingerprints


def draft(source="return a+b", tests="def test_one(): pass"):
    def file(path, content):
        return {"path": path, "content": content,
                "sha256": hashlib.sha256(content.encode()).hexdigest()}

    return {"draft": {"files": [file("math_ops.py", source), file("test_math_ops.py", tests)]}}


def test_acceptance_hash_from_actual_bytes():
    assert "test_math_ops.py" in fingerprints(draft())


def test_tampered_test_hash_rejected():
    item = draft()
    item["draft"]["files"][1]["sha256"] = "0" * 64
    with pytest.raises(RunStopped):
        fingerprints(item)


def test_test_edit_rejected():
    original = draft()
    with pytest.raises(RunStopped, match="acceptance tests"):
        verify_source_policy(original, draft(tests="def test_two(): pass"), fingerprints(original))


def test_noop_rejected():
    original = draft()
    with pytest.raises(RunStopped, match="unapproved source"):
        verify_source_policy(original, draft(), fingerprints(original))


def test_valid_one_file_replacement():
    original = draft()
    verify_source_policy(original, draft(source="return a*b"), fingerprints(original))


def test_new_files_rejected():
    original = draft()
    child = draft(source="return a*b")
    child["draft"]["files"].append({"path": "new.py", "content": "x = 1", "sha256": hashlib.sha256(b"x = 1").hexdigest()})
    with pytest.raises(RunStopped, match="inventory"):
        verify_source_policy(original, child, fingerprints(original))


class FakeAPI:
    def __init__(self, *, passing=False):
        self.passing = passing
        self.events = []
        self.child = draft(source="return a*b") | {"id": "22222222-2222-2222-2222-222222222222", "status": "review"}
        self.parent = draft() | {"id": "11111111-1111-1111-1111-111111111111", "status": "completed"}

    def call(self, path, *, post=False):
        self.events.append((path, post))
        if path == "status":
            return {"project_mode_enabled": True, "sandbox_verify_enabled": True}
        if path == "projects/11111111-1111-1111-1111-111111111111":
            return self.parent
        if path.endswith("/verification"):
            return {"status": "completed", "result": {"executed": True,
                    "passed": self.passing, "outcome": "passed" if self.passing else "failed",
                    "tests_run": 1}}
        if path.endswith("/repair") and not post:
            return {"status": "completed", "result": {"review_required": True, "executed": False}}
        if path.endswith("/repair/use"):
            assert post
            return self.child
        if path.endswith("/apply"):
            assert post
            self.child["status"] = "completed"
            return self.child
        if path == "projects/22222222-2222-2222-2222-222222222222":
            return self.child
        raise AssertionError(path)


def test_passing_project_no_mutations():
    api = FakeAPI(passing=True)
    result = run_cycle(api, "11111111-1111-1111-1111-111111111111")
    assert result["outcome"] == "passed"
    assert not any(post for _, post in api.events)


def test_one_repair_limit_and_immutable_tests():
    api = FakeAPI()
    result = run_cycle(api, "11111111-1111-1111-1111-111111111111", attempts=1)
    assert result["outcome"] == "repair_limit"
    assert sum(post for _, post in api.events) == 2  # promote + apply, reuse existing proposal
    assert result["attempts"] == 1


def test_invalid_attempts_stopped():
    with pytest.raises(RunStopped):
        run_cycle(FakeAPI(), "11111111-1111-1111-1111-111111111111", attempts=4)
