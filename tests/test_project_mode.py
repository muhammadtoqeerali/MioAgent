"""End-to-end API and filesystem policy checks; no GPUs, network, or paid APIs."""

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mio.api import create_app
from mio.config import Settings
from mio.llm import Completion, ModelRouter
from mio.project_mode import (
    ProjectPolicyError,
    apply_draft,
    check_private_root,
    validate_draft,
    verify_existing_project,
)

SAMPLE = json.dumps({"plan": ["Create a tiny app", "Add example usage"], "files": [
    {"path": "src/hello.py", "content": "def greet(name):\n    return f'Hi {name}'\n"},
    {"path": "README.md", "content": "# Sample app\n"},
    {"path": "data/example.json", "content": '{"name":"Mio"}'},
]})
PROJECT_ID = "01234567-1234-5678-9abc-0123456789ab"


def test_draft_static_validation():
    draft = validate_draft(SAMPLE)
    assert len(draft["files"]) == 3
    assert any("Python syntax" in entry for entry in draft["checks"])
    assert any("JSON syntax" in entry for entry in draft["checks"])
    assert draft["verification"].startswith("static checks only")


@pytest.mark.parametrize("bad_path", [
    "/etc/passwd", "../private.py", "x/../../bad.py", "x\\evil.py", ".env",
    ".git/config.json", "src/.hidden.py", "src//bad.py", "C:/windows.py", "evil.exe",
])
def test_rejects_unsafe_paths(bad_path):
    malicious = json.dumps({"plan": ["One"], "files": [
        {"path": bad_path, "content": "print('test')"}
    ]})
    with pytest.raises(ProjectPolicyError):
        validate_draft(malicious)


def test_rejects_excessive_files_and_invalid_source():
    with pytest.raises(ProjectPolicyError, match="1 to 6"):
        validate_draft(json.dumps({"plan": ["One"], "files": [
            {"path": f"file{i}.py", "content": "x=1"} for i in range(7)
        ]}))
    with pytest.raises(ProjectPolicyError, match="syntax"):
        validate_draft(json.dumps({"plan": ["One"], "files": [
            {"path": "main.py", "content": "def bad(:"}
        ]}))
    with pytest.raises(ProjectPolicyError, match="per-file"):
        validate_draft(json.dumps({"plan": ["One"], "files": [
            {"path": "big.txt", "content": "a" * 20000}
        ]}))


def test_guarded_apply_and_verify(tmp_path, monkeypatch):
    from mio import project_mode as pm
    monkeypatch.setattr(pm, "_mount_type", lambda path: "ext4")
    root = tmp_path / "projects"
    draft = validate_draft(SAMPLE)
    applied = apply_draft(root, PROJECT_ID, draft)
    assert applied["executed"] is False
    assert applied["workspace"] == str(root / PROJECT_ID)
    assert (root / PROJECT_ID / "src/hello.py").read_text().startswith("def greet")
    assert check_private_root(root) == root.resolve()
    resumed = verify_existing_project(root, PROJECT_ID, draft)
    assert resumed and resumed["resumed"] is True
    with pytest.raises(ProjectPolicyError, match="already exists"):
        apply_draft(root, PROJECT_ID, draft)
    (root / PROJECT_ID / "src/hello.py").write_text("tampered")
    with pytest.raises(ProjectPolicyError, match="differ"):
        verify_existing_project(root, PROJECT_ID, draft)


def test_refuse_insecure_and_symlink_roots(tmp_path, monkeypatch):
    from mio import project_mode as pm
    monkeypatch.setattr(pm, "_mount_type", lambda path: "cifs")
    with pytest.raises(ProjectPolicyError, match="native Linux"):
        check_private_root(tmp_path / "projects")
    monkeypatch.setattr(pm, "_mount_type", lambda path: "ext4")
    root = tmp_path / "open"
    root.mkdir(mode=0o777)
    root.chmod(0o777)
    with pytest.raises(ProjectPolicyError, match="0700"):
        check_private_root(root)
    link = tmp_path / "link"
    link.symlink_to(root)
    with pytest.raises(ProjectPolicyError, match="symlink"):
        check_private_root(link)


def test_api_disabled_by_default(tmp_path):
    settings = Settings(mio_api_token="q" * 48,
                        mio_database_url=f"sqlite+pysqlite:///{tmp_path / 'disabled.db'}")
    headers = {"Authorization": "Bearer " + settings.mio_api_token}
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/projects", headers=headers).status_code == 409
        assert client.post("/api/projects", headers=headers, json={
            "title": "Example", "requirements": "Please build a local mini app."
        }).status_code == 409


def _await_status(client, headers, project_id, statuses, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/projects/{project_id}", headers=headers)
        assert response.status_code == 200, response.text
        data = response.json()
        if data["status"] in statuses:
            return data
        time.sleep(0.05)
    raise AssertionError(f"Project didn't reach {statuses}: {data}")


def test_project_draft_approval_and_recovery(tmp_path, monkeypatch):
    from mio import project_mode as pm
    monkeypatch.setattr(pm, "_mount_type", lambda path: "ext4")

    async def fake_complete(self, messages, max_tokens=768):
        assert self.providers()[0][0] == "local"
        assert all(p[0] == "local" for p in self.providers())
        assert "DRAFTING" in messages[0]["content"]
        return Completion(SAMPLE, "local", "mock-local", 14, 30)

    monkeypatch.setattr(ModelRouter, "complete", fake_complete)
    settings = Settings(
        mio_api_token="a" * 48,
        mio_database_url=f"sqlite+pysqlite:///{tmp_path / 'project.db'}",
        mio_workspace_root=tmp_path,
        mio_local_model="mock-local",
        mio_allow_cloud=True,
        mio_cloud_model="no-cloud-call",
        mio_cloud_api_key="unused-secret",
        mio_model_route="cloud",
        mio_enable_project_mode=True,
        mio_project_root=tmp_path / "artifacts",
        mio_poll_seconds=0.1,
    )
    headers = {"Authorization": "Bearer " + settings.mio_api_token}
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/projects").status_code == 401
        created = client.post("/api/projects", headers=headers, json={
            "title": "Minimal Python App", "requirements": "Build a small Python sample with a README."
        })
        assert created.status_code == 202, created.text
        pid = created.json()["id"]
        drafted = _await_status(client, headers, pid, {"review", "failed"})
        assert drafted["status"] == "review", drafted
        assert len(drafted["draft"]["files"]) == 3
        assert not (settings.mio_project_root / pid).exists()
        assert client.get("/api/projects", headers=headers).json()["projects"]
        assert client.post(f"/api/projects/{pid}/apply", headers=headers,
                           json={"approved": False}).status_code == 422
        accepted = client.post(f"/api/projects/{pid}/apply", headers=headers,
                               json={"approved": True})
        assert accepted.status_code == 202, accepted.text
        assert client.post(f"/api/projects/{pid}/apply", headers=headers,
                           json={"approved": True}).status_code == 409
        applied = _await_status(client, headers, pid, {"completed", "failed"})
        assert applied["status"] == "completed", applied
        assert Path(applied["workspace"]).is_dir()
        assert (Path(applied["workspace"]) / "src/hello.py").is_file()
        task = client.get(f"/api/tasks/{applied['apply_task_id']}", headers=headers).json()
        assert task["status"] == "completed"
        assert task["result"]["executed"] is False
    with TestClient(create_app(settings)) as client:
        persisted = client.get(f"/api/projects/{pid}", headers=headers).json()
        assert persisted["status"] == "completed"
        assert persisted["draft"]["checks"]
