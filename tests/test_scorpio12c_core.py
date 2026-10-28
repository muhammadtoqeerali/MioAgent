"""S12C persistent offline coding control plane and owner-only API tests."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from mio.scorpio12c_api import register_scorpio12c_routes
from mio.scorpio12c_core import (
    CASES,
    CodingStop,
    cancel_job,
    create_job,
    execute_job,
    list_jobs,
    read_job,
    status,
)


@pytest.fixture
def root():
    base = Path(f"/var/tmp/mioagent-native-{os.getuid()}")
    if not base.is_dir():
        pytest.skip("Existing private native runtime required")
    with tempfile.TemporaryDirectory(dir=base, prefix="s12c-tests-") as td:
        parent = Path(td)
        parent.chmod(0o700)
        # Store requires direct native-runtime child, not nested folder.
        # Reuse the unique temporary directory directly.
        yield parent


def test_status_truthful():
    state = status()
    assert not state["llm_autonomy"]
    assert not state["model_inference_enabled"]
    assert not state["owner_repo_apply_enabled"]
    assert len(state["case_options"]) == 3


def test_reject_unknown_case(root):
    with pytest.raises(CodingStop, match="Only platform"):
        create_job("/usr/share/ollama", root=root)
    with pytest.raises(CodingStop, match="Invalid"):
        read_job("bad", root=root)


@pytest.mark.parametrize("case", list(CASES))
def test_true_bwrap_simulated_recovery_persists(case, root):
    job = create_job(case, root=root)
    assert job["state"] == "draft"
    result = execute_job(job["id"], root=root)
    assert result["state"] == "verified_rehearsal", result
    evidence = result["result"]
    assert evidence["kind"] == "deterministic_simulation"
    assert [a["passed"] for a in evidence["attempts"]] == [False, True]
    assert all(a["selected_tests_run"] for a in evidence["attempts"])
    assert evidence["original_unchanged"] is True
    assert evidence["applied_to_owner_repository"] is False
    assert len(evidence["audit_sha256"]) == 64
    assert read_job(job["id"], root=root)["state"] == "verified_rehearsal"
    assert list_jobs(root=root)["jobs"]
    with pytest.raises(CodingStop, match="unstarted"):
        execute_job(job["id"], root=root)


def test_owner_cancel_before_execution(root):
    job = create_job("arithmetic", root=root)
    canceled = cancel_job(job["id"], root=root)
    assert canceled["state"] == "canceled"
    with pytest.raises(CodingStop, match="unstarted"):
        execute_job(job["id"], root=root)
    with pytest.raises(CodingStop, match="Only a draft"):
        cancel_job(job["id"], root=root)


def test_api_auth_and_no_arbitrary_repo_tools(root):
    app = FastAPI()
    def require_token(authorization: str | None = Header(default=None)):
        if authorization != "Bearer test-token":
            raise HTTPException(401, "Unauthorized")
    register_scorpio12c_routes(app, require_token, root=root)
    client = TestClient(app)
    assert client.get("/api/scorpio/coding/status").status_code == 401
    headers = {"Authorization": "Bearer test-token"}
    response = client.get("/api/scorpio/coding/status", headers=headers)
    assert response.status_code == 200
    assert response.json()["mode"] == "offline_rehearsal_only"
    assert client.post("/api/scorpio/coding/jobs", headers=headers,
                       json={"case_name": "arithmetic", "approved": False}).status_code == 422
    assert client.post("/api/scorpio/coding/jobs", headers=headers,
                       json={"case_name": "/mnt/secret", "approved": True}).status_code == 422
    job = client.post("/api/scorpio/coding/jobs", headers=headers,
                      json={"case_name": "arithmetic", "approved": True})
    assert job.status_code == 201
    item = job.json()
    assert client.post(f"/api/scorpio/coding/jobs/{item['id']}/execute", headers=headers,
                       json={"approved": False}).status_code == 422
    assert client.post(f"/api/scorpio/coding/jobs/{item['id']}/cancel", headers=headers,
                       json={"approved": True}).status_code == 200
    assert client.get(f"/api/scorpio/coding/jobs/{item['id']}", headers=headers).json()["state"] == "canceled"


def test_dashboard_brand_preserves_real_fallback_and_primary_png():
    """Gold logo uses <picture>; original SVG remains genuine fallback."""
    root = Path(__file__).resolve().parents[1]
    shell = (root / "apps/dashboard/app/_mio/scorpio8a-shell.tsx").read_text()
    assert '<picture>' in shell and '<source srcSet="/scorpio-brand-gold.png?v=12c"' in shell
    assert '<img src="/scorpio-mark.svg?v=8c"' in shell
    assert "AI AGENT PLATFORM" in shell
    image = root / "apps/dashboard/public/scorpio-brand-gold.png"
    assert image.is_file() and image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
