"""v0.4F dashboard: private read-only runtime evidence and authenticated endpoints."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from mio import dashboard_insights as insights
from mio.api import create_app
from mio.config import Settings

D = "a" * 64


def workspace(tmp_path: Path, monkeypatch):
    root = tmp_path / "runtime"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(insights, "RUNTIME", root)
    repo = root / "repo-engineering"
    repo.mkdir(mode=0o700)
    record = repo / D
    record.mkdir(mode=0o700)
    (record / "report.json").write_text(json.dumps({
        "goal_sha256": D, "state": "passed", "model": "gpt-oss:20b",
        "created_unix": 8, "tests_run": 5,
        "attempts": [{"changed_files": ["lab/metrics.py"]}],
    }), encoding="utf-8")
    (record / "report.json").chmod(0o600)
    (record / "changes.patch").write_text("--- a/lab/metrics.py\n+++ b/lab/metrics.py\n", encoding="utf-8")
    (record / "changes.patch").chmod(0o600)
    return root, record


def test_lists_valid_run_and_reads_patch(tmp_path, monkeypatch):
    root, _ = workspace(tmp_path, monkeypatch)
    runs = insights.list_repo_runs(root)
    assert len(runs) == 1
    assert runs[0]["state"] == "passed"
    assert runs[0]["tests_run"] == 5
    assert runs[0]["patch_available"] is True
    assert "+++ b/lab/metrics.py" in insights.verified_patch(root, D)["patch"]


def test_rejects_symlink_patch(tmp_path, monkeypatch):
    root, record = workspace(tmp_path, monkeypatch)
    (record / "changes.patch").unlink()
    (record / "changes.patch").symlink_to(record / "report.json")
    assert insights.list_repo_runs(root)[0]["patch_available"] is False
    with pytest.raises(HTTPException) as exc:
        insights.verified_patch(root, D)
    assert exc.value.status_code == 404


def test_rejects_path_traversal_and_private_metadata(tmp_path, monkeypatch):
    root, record = workspace(tmp_path, monkeypatch)
    with pytest.raises(HTTPException):
        insights.verified_patch(root, "../etc/passwd")
    (record / "report.json").chmod(0o644)
    assert insights.list_repo_runs(root) == []
    with pytest.raises(HTTPException):
        insights.verified_patch(root, D)


def test_no_files_is_safe(tmp_path):
    assert insights.list_repo_runs(tmp_path) == []
    assert insights.list_goal_runs(tmp_path) == []


def test_authenticated_api_returns_real_run_and_no_write_routes(tmp_path, monkeypatch):
    workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(insights, "inventory", AsyncMock(return_value={
        "gpt-oss:20b": {"size_bytes": 13_000_000_000, "digest": "b" * 64}
    }))
    monkeypatch.setattr(insights, "load_policy", lambda: None)
    settings = Settings(_env_file=None, mio_api_token="x" * 48,
                        mio_database_url=f"sqlite+pysqlite:///{tmp_path / 'test.db'}",
                        mio_workspace_root=tmp_path, mio_poll_seconds=0.1)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/intelligence/overview").status_code == 401
        auth = {"Authorization": "Bearer " + settings.mio_api_token}
        summary = client.get("/api/intelligence/overview", headers=auth)
        assert summary.status_code == 200, summary.text
        assert summary.json()["repo_runs"][0]["tests_run"] == 5
        assert summary.json()["read_only"] is True
        assert summary.json()["models"][0]["id"] == "gpt-oss:20b"
        assert client.get(f"/api/intelligence/repository/{D}/patch").status_code == 401
        assert client.get(f"/api/intelligence/repository/{D}/patch", headers=auth).status_code == 200
        assert client.post("/api/intelligence/overview", headers=auth).status_code == 405
