"""SCORPIO9D3B7: only owner-approved Work requests may claim one browser grant."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from mio import scorpio9d3b7_work_browser as browser
from mio.work_api import register_work_routes
from mio.work_core import WorkStop, create_project, db, run_info

URL = "https://www.python.org/"


def root(tmp_path: Path) -> Path:
    private = tmp_path / "owner-private"
    private.mkdir(mode=0o700)
    return private / "work"


def project_run(tmp_path):
    base = root(tmp_path)
    project = create_project(base, "Research project", "Cite verified sources")
    proposed = browser.propose(base, project=project["id"],
                               goal="Inspect public Python documentation", url=URL)
    return base, project, proposed


def test_proposal_has_no_grant_or_queued_run(tmp_path):
    base, project, proposal = project_run(tmp_path)
    assert proposal["decision"] == "proposed"
    assert proposal["state"] == "needs_review"
    assert proposal["mode"] == "browser_proposed"
    assert proposal["project"] == project["id"]
    assert browser.broker_directory(base).exists() is False
    with db(base) as conn:
        assert conn.execute("SELECT count(*) FROM runs WHERE state='queued'").fetchone()[0] == 0


def test_bad_urls_and_invalid_goal_never_stage(tmp_path):
    base = root(tmp_path)
    proj = create_project(base, "Project", "")
    for url in ("http://example.com", "https://localhost", "https://127.0.0.1/",
                "file:///etc/passwd", "https://user:pass@example.com/"):
        with pytest.raises(WorkStop):
            browser.propose(base, project=proj["id"], goal="Check external documentation", url=url)
    with pytest.raises(WorkStop):
        browser.propose(base, project=proj["id"], goal="no", url=URL)


def test_reject_no_grant_and_no_execution(tmp_path):
    base, _, pending = project_run(tmp_path)
    with patch.object(browser, "issue_one_use") as issue:
        result = browser.decide(base, run=pending["run"], approve=False)
    issue.assert_not_called()
    assert result["state"] == "failed"
    assert result["decision"] == "rejected"
    assert "browser.rejected" in [e["phase"] for e in run_info(base, pending["run"])["events"]]
    with pytest.raises(WorkStop):
        browser.decide(base, run=pending["run"], approve=True)


def test_authentication_required_for_all_browser_routes(tmp_path):
    base = root(tmp_path)
    project = create_project(base, "Research", "")
    app = FastAPI()

    def auth(authorization: str | None = Header(default=None)):
        if authorization != "Bearer owner":
            raise HTTPException(401)

    register_work_routes(app, SimpleNamespace(), auth, base)
    with TestClient(app) as client:
        endpoint = f"/api/work/projects/{project['id']}/browser-proposals"
        assert client.post(endpoint, json={"prompt": "Research Python docs", "url": URL}).status_code == 401
        h = {"Authorization": "Bearer owner"}
        proposal = client.post(endpoint, headers=h,
                               json={"prompt": "Research Python docs", "url": URL})
        assert proposal.status_code == 201
        run = proposal.json()["run"]
        assert client.get(f"/api/work/runs/{run}/browser-proposal").status_code == 401
        assert client.post(f"/api/work/runs/{run}/browser-decision",
                           json={"approve": True}).status_code == 401
        assert client.get(f"/api/work/runs/{run}/browser-proposal", headers=h).json()["url"] == URL
        assert client.post(f"/api/work/runs/{run}/browser-decision", headers=h,
                           json={"approve": False}).json()["decision"] == "rejected"


def test_approval_exact_binding_once(tmp_path):
    base, proj, pending = project_run(tmp_path)
    with patch.object(browser, "issue_one_use", return_value="a" * 64) as issue:
        granted = browser.decide(base, run=pending["run"], approve=True)
    issue.assert_called_once_with(browser.broker_directory(base), project=proj["id"],
                                  run=pending["run"], url=URL, owner_approved=True, ttl=180)
    assert granted["state"] == "queued"
    assert granted["decision"] == "approved"
    assert "token" not in granted
    with pytest.raises(WorkStop, match="already decided"):
        browser.decide(base, run=pending["run"], approve=True)
    with db(base) as conn:
        row = conn.execute("SELECT token FROM scorpio9d3b7_browser_proposals").fetchone()
    assert row["token"] == "a" * 64


def test_worker_finishes_valid_approved_grant(tmp_path):
    base, proj, pending = project_run(tmp_path)
    with patch.object(browser, "issue_one_use", return_value="a" * 64):
        browser.decide(base, run=pending["run"], approve=True)
    report = {"state": "verified", "browser_network": "disabled",
              "javascript_executed": True, "page_sha256": "b" * 64,
              "rendered_sha256": "c" * 64}
    with patch.object(browser, "execute_granted", return_value=report) as execute:
        result = browser.maybe_execute_browser(base, pending["run"], run_info(base, pending["run"]))
    execute.assert_called_once_with(browser.broker_directory(base), project=proj["id"],
                                    run=pending["run"], url=URL, token="a" * 64)
    assert result["state"] == "answered"
    assert result["mode"] == "browser_verified"
    assert result["sources"][0]["page_verified"] is True
    assert result["sources"][0]["page_sha256"] == "b" * 64
    assert "browser.verified" in [e["phase"] for e in result["events"]]
    with db(base) as conn:
        row = conn.execute("SELECT consumed,token FROM scorpio9d3b7_browser_proposals").fetchone()
    assert (row["consumed"], row["token"]) == (1, None)
    assert browser.maybe_execute_browser(base, pending["run"], result) is None


def test_worker_failure_stops_without_model_fallback(tmp_path):
    base, _, pending = project_run(tmp_path)
    with patch.object(browser, "issue_one_use", return_value="a" * 64):
        browser.decide(base, run=pending["run"], approve=True)
    with patch.object(browser, "execute_granted", side_effect=RuntimeError("untrusted error")):
        result = browser.maybe_execute_browser(base, pending["run"], run_info(base, pending["run"]))
    assert result["state"] == "needs_review"
    assert result["mode"] == "browser_denied"
    assert "untrusted error" not in str(result)
    with db(base) as conn:
        row = conn.execute("SELECT consumed,token FROM scorpio9d3b7_browser_proposals").fetchone()
    assert (row["consumed"], row["token"]) == (1, None)
    with pytest.raises(WorkStop):
        browser._claim_worker(base, pending["run"])


def test_unapproved_or_wrong_run_cannot_claim(tmp_path):
    base, _, pending = project_run(tmp_path)
    with pytest.raises(WorkStop):
        browser._claim_worker(base, pending["run"])
    with pytest.raises(WorkStop):
        browser._claim_worker(base, "f" * 32)
    assert browser.maybe_execute_browser(base, pending["run"], run_info(base, pending["run"])) is None


def test_corrupted_binding_refused_without_browser_network(tmp_path):
    base, _, pending = project_run(tmp_path)
    with patch.object(browser, "issue_one_use", return_value="a" * 64):
        browser.decide(base, run=pending["run"], approve=True)
    with db(base) as conn:
        conn.execute("UPDATE scorpio9d3b7_browser_proposals SET token=NULL WHERE run=?",
                     (pending["run"],))
    with patch.object(browser, "execute_granted") as executor:
        result = browser.maybe_execute_browser(base, pending["run"], run_info(base, pending["run"]))
    executor.assert_not_called()
    assert result["state"] == "needs_review"


def test_active_work_queue_blocks_approval(tmp_path):
    base, proj, pending = project_run(tmp_path)
    from mio.work_core import create_run
    active = create_run(base, proj["id"], "Summarize research evidence")
    assert active["state"] == "queued"
    with (patch.object(browser, "issue_one_use") as issue,
          pytest.raises(WorkStop, match="queue busy")):
        browser.decide(base, run=pending["run"], approve=True)
    issue.assert_not_called()


def test_invalid_run_and_mode_never_invoke_browser(tmp_path):
    base, _, pending = project_run(tmp_path)
    with pytest.raises(WorkStop):
        browser.proposal_info(base, "../../etc")
    with patch.object(browser, "execute_granted") as execute:
        assert browser.maybe_execute_browser(base, pending["run"], {"mode": "pending"}) is None
    execute.assert_not_called()


def test_broker_claim_consumes_before_network(tmp_path):
    base, _, pending = project_run(tmp_path)
    with patch.object(browser, "issue_one_use", return_value="a" * 64):
        browser.decide(base, run=pending["run"], approve=True)

    def inspect_before_network(*args, **kwargs):
        with db(base) as conn:
            row = conn.execute("SELECT consumed,token FROM scorpio9d3b7_browser_proposals").fetchone()
        assert (row["consumed"], row["token"]) == (1, None)
        raise RuntimeError("test network blocked")

    with patch.object(browser, "execute_granted", side_effect=inspect_before_network):
        result = browser.maybe_execute_browser(base, pending["run"], run_info(base, pending["run"]))
    assert result["state"] == "needs_review"


def test_database_declares_one_proposal_per_run(tmp_path):
    base, _, pending = project_run(tmp_path)
    with (db(base) as conn, pytest.raises(sqlite3.IntegrityError)):
        conn.execute("INSERT INTO scorpio9d3b7_browser_proposals "
                     "(run,project,url,decision,created) VALUES (?,?,?,?,?)",
                     (pending["run"], pending["project"], URL, "proposed", 0))
