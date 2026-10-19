"""v0.4G: owner registration, authenticated launch, SHA-bound review and replay guards."""

import hashlib
import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from mio import dashboard_jobs as jobs
from mio.api import create_app
from mio.config import Settings


def fixture(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(jobs, "RUNTIME", root)
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "core.py").write_text("def add(a,b):\n    return a-b\n")
    (repository / "test_core.py").write_text(
        "import unittest\nfrom core import add\nclass T(unittest.TestCase):\n    def test_add(self): assert add(2,3)==5\n"
    )
    contract = tmp_path / "input.json"
    contract.write_text(json.dumps({"repository": str(repository),
        "task": "Fix the existing addition bug, preserving the test.",
        "editable_files": ["core.py"], "acceptance_tests": ["test_core.py"], "max_attempts": 2}))
    return root, repository, contract


def test_register_and_read_immutable_contract(tmp_path, monkeypatch):
    _, repo, contract = fixture(tmp_path, monkeypatch)
    recorded = jobs.register_goal(contract)
    assert recorded["editable_files"] == ["core.py"]
    assert jobs.goal_info(recorded["id"])["run_state"] is None
    assert len(jobs.list_goals()) == 1
    with pytest.raises(jobs.RepoStop):
        jobs.register_goal(contract)
    with pytest.raises(jobs.RepoStop):
        jobs.approved_goal("../etc/passwd")
    (repo / "test_core.py").write_text("# edited\n")
    with pytest.raises(jobs.RepoStop, match="changed"):
        jobs.approved_goal(recorded["id"])
    assert jobs.list_goals() == []


def test_unauthorized_and_explicit_browser_launch(tmp_path, monkeypatch):
    _, _, contract = fixture(tmp_path, monkeypatch)
    identifier = jobs.register_goal(contract)["id"]
    started = []

    class FakeProc:
        def wait(self):
            return 0

    def fake_popen(argv, **kwargs):
        started.append((argv, kwargs))
        return FakeProc()

    monkeypatch.setattr(jobs.subprocess, "Popen", fake_popen)
    settings = Settings(_env_file=None, mio_api_token="X" * 48,
                        mio_database_url=f"sqlite+pysqlite:///{tmp_path / 'backend.db'}",
                        mio_workspace_root=tmp_path, mio_poll_seconds=.1)
    with TestClient(create_app(settings)) as client:
        url = f"/api/intelligence/goals/{identifier}/start"
        header = {"Authorization": f"Bearer {settings.mio_api_token}"}
        assert client.post(url, json={"approved": True}).status_code == 401
        assert client.post(url, json={"approved": False}, headers=header).status_code == 422
        assert client.post(url, json={"approved": True}, headers=header).status_code == 202
        assert client.post(url, json={"approved": True}, headers=header).status_code == 409
        assert client.get("/api/intelligence/goals", headers=header).json()["goals"][0]["id"] == identifier
        assert client.get(f"/api/intelligence/goals/{identifier}/status", headers=header).status_code == 200
    assert len(started) == 1
    argv, kwargs = started[0]
    assert argv[-2:] == [identifier, "run"]
    assert kwargs["stdin"] is not None
    assert kwargs["start_new_session"] is True
    assert "shell" not in kwargs


def test_apply_requires_same_verified_patch_digest(tmp_path, monkeypatch):
    root, _, contract = fixture(tmp_path, monkeypatch)
    identity = jobs.register_goal(contract)["id"]
    folder = root / "repo-engineering" / identity
    folder.mkdir(parents=True, mode=0o700)
    report = folder / "report.json"
    report.write_text(json.dumps({"goal_sha256": identity, "state": "passed", "tests_run": 1}), encoding="utf8")
    report.chmod(0o600)
    patch = folder / "changes.patch"
    patch.write_text("--- a/core.py\n+++ b/core.py\n")
    patch.chmod(0o600)
    with pytest.raises(jobs.RepoStop, match="Patch changed"):
        jobs.launch(identity, "apply", "0" * 64)
    # The API may start the registered worker only with the digest of the read patch.
    fake = Mock()
    fake.wait.return_value = 0
    monkeypatch.setattr(jobs.subprocess, "Popen", Mock(return_value=fake))
    result = jobs.launch(identity, "apply", hashlib.sha256(patch.read_bytes()).hexdigest())
    assert result["action"] == "apply"
    with pytest.raises(jobs.RepoStop):
        jobs.launch(identity, "apply", hashlib.sha256(patch.read_bytes()).hexdigest())


def test_goal_registration_rejects_source_symlink(tmp_path, monkeypatch):
    _, _, contract = fixture(tmp_path, monkeypatch)
    link = tmp_path / "symlink.json"
    link.symlink_to(contract)
    with pytest.raises(jobs.RepoStop):
        jobs.register_goal(link)


def test_runner_cannot_execute_unregistered_hash(tmp_path, monkeypatch):
    fixture(tmp_path, monkeypatch)
    with pytest.raises(jobs.RepoStop):
        jobs.approved_goal("a" * 64)


def test_private_job_record_and_log(tmp_path, monkeypatch):
    root, _, contract = fixture(tmp_path, monkeypatch)
    digest = jobs.register_goal(contract)["id"]
    fake = Mock()
    fake.wait.return_value = 0
    monkeypatch.setattr(jobs.subprocess, "Popen", Mock(return_value=fake))
    jobs.launch(digest, "run")
    status = root / "dashboard-jobs" / f"{digest}.run.json"
    log = root / "dashboard-jobs" / f"{digest}.run.log"
    assert status.stat().st_mode & 0o077 == 0
    assert log.stat().st_mode & 0o077 == 0
    log.write_text("=== TEST 5 PASS ===")
    assert jobs.log_tail(digest, "run") == "=== TEST 5 PASS ==="
    with pytest.raises(jobs.RepoStop):
        jobs.log_tail("../escape", "run")
