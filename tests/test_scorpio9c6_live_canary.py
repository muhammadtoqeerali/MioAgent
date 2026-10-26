"""SCORPIO9C6: production opt-in gates exercised on isolated synthetic Work DBs."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from mio import scorpio9c4_worker_tool
from mio import scorpio9c6_live_canary as canary
from mio.supervisor_core import advance_supervisor, approve_plan, pause_plan
from mio.work_core import WorkStop, create_project, create_run, db, run_info


@pytest.fixture
def scope(tmp_path, monkeypatch):
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    root = parent / "work"
    # Create only an isolated test Work schema. Never open native Work runtime.
    with db(root):
        pass
    monkeypatch.setattr(os, "isatty", lambda _fd: True)
    return root, parent


def test_no_database_is_created_by_readiness(tmp_path):
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    target = parent / "work"
    with pytest.raises(WorkStop):
        canary.readiness(target)
    assert not target.exists()


def test_owner_console_refuses_injected_root(scope):
    root, _parent = scope
    with pytest.raises(WorkStop, match="fixed native"):
        canary.prepare_canary(root)


def test_readiness_is_readonly(scope):
    root, _parent = scope
    before = (root / "work.db").read_bytes()
    result = canary.readiness(root)
    assert result["read_only"] is True
    assert result["eligible_for_separate_owner_canary"] is True
    assert result["existing_projects"] == 0
    assert (root / "work.db").read_bytes() == before


def test_prepare_only_stages_a_draft_and_private_backup(scope):
    root, parent = scope
    result = canary._prepare_canary(root)
    assert result["status"] == "draft_waiting_independent_owner_approval"
    assert result["automatic_approval"] is False
    assert result["worker_started_by_canary"] is False
    backup = Path(result["backup"])
    assert backup.is_file() and backup.stat().st_mode & 0o077 == 0
    assert backup.parent == parent / "scorpio9c6-canary-backups"
    synthetic = parent / "tool-inputs" / result["project_id"] / canary.CANARY_FILE
    assert synthetic.read_bytes() == canary.CANARY_BYTES
    assert synthetic.stat().st_mode & 0o077 == 0
    with db(root) as conn:
        plan = conn.execute("SELECT state FROM supervisor_plans WHERE id=?", (result["plan_id"],)).fetchone()
        assert plan["state"] == "draft"
        assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM scorpio9c_step_bindings").fetchone()[0] == 1
    check = canary.verify_canary(result["project_id"], result["plan_id"], root)
    assert check["outcome"] == "waiting_for_owner_approval"
    assert check["grant_consumed"] is False
    assert canary.CANARY_SHA256 == hashlib.sha256(canary.CANARY_BYTES).hexdigest()


def test_duplicate_canary_refused_without_mutation(scope):
    root, _parent = scope
    canary._prepare_canary(root)
    result = canary.readiness(root)
    assert result["existing_canaries"] == 1
    assert not result["eligible_for_separate_owner_canary"]
    with pytest.raises(WorkStop, match="prior canary"):
        canary._prepare_canary(root)
    with db(root) as conn:
        assert conn.execute("SELECT count(*) FROM projects").fetchone()[0] == 1


def test_new_canary_denied_when_other_work_queued(scope):
    root, _parent = scope
    project = create_project(root, "Existing operator task", "Owner created")
    create_run(root, project["id"], "Research the bounded owner request")
    assert canary.readiness(root)["active_work_runs"] == 1
    with pytest.raises(WorkStop):
        canary._prepare_canary(root)


def test_success_requires_separate_plan_approval_and_exact_audit(scope, monkeypatch):
    root, _parent = scope
    item = canary._prepare_canary(root)
    assert canary.verify_canary(item["project_id"], item["plan_id"], root)["outcome"] == "waiting_for_owner_approval"
    approve_plan(root, item["plan_id"])
    run_id = advance_supervisor(root)
    assert run_id
    assert canary.verify_canary(item["project_id"], item["plan_id"], root)["outcome"] == "pending_worker_or_review"
    monkeypatch.setattr(scorpio9c4_worker_tool, "_sandbox_digest", scorpio9c4_worker_tool._digest)
    run = scorpio9c4_worker_tool.maybe_execute_scoped_tool(root, run_id, run_info(root, run_id))
    assert run["state"] == "answered"
    assert advance_supervisor(root) is None
    result = canary.verify_canary(item["project_id"], item["plan_id"], root)
    assert result["outcome"] == "passed_real_managed_worker"
    assert result["run_verified_events"] == 1 and result["run_claim_events"] == 1
    assert result["grant_consumed"] is True


def test_verify_fails_closed_on_missing_verification_event(scope, monkeypatch):
    root, _parent = scope
    item = canary._prepare_canary(root)
    approve_plan(root, item["plan_id"])
    run_id = advance_supervisor(root)
    monkeypatch.setattr(scorpio9c4_worker_tool, "_sandbox_digest", scorpio9c4_worker_tool._digest)
    assert scorpio9c4_worker_tool.maybe_execute_scoped_tool(root, run_id, run_info(root, run_id))["state"] == "answered"
    advance_supervisor(root)
    with db(root) as conn:
        conn.execute("DELETE FROM events WHERE run=? AND phase='tool.verified'", (run_id,))
    with pytest.raises(WorkStop, match="lacks exact"):
        canary.verify_canary(item["project_id"], item["plan_id"], root)


def test_revoked_grant_does_not_report_success(scope):
    root, _parent = scope
    item = canary._prepare_canary(root)
    with db(root) as conn:
        conn.execute("UPDATE scorpio9c_grants SET revoked=1 WHERE id=?", (item["grant_id"],))
    approve_plan(root, item["plan_id"])
    run_id = advance_supervisor(root)
    result = scorpio9c4_worker_tool.maybe_execute_scoped_tool(root, run_id, run_info(root, run_id))
    assert result["state"] == "needs_review"
    advance_supervisor(root)
    detail = canary.verify_canary(item["project_id"], item["plan_id"], root)
    assert detail["outcome"] == "denied_owner_review_required"
    assert detail["grant_consumed"] is False


def test_paused_plan_does_not_claim_grant(scope):
    root, _parent = scope
    item = canary._prepare_canary(root)
    approve_plan(root, item["plan_id"])
    run_id = advance_supervisor(root)
    pause_plan(root, item["plan_id"])
    result = scorpio9c4_worker_tool.maybe_execute_scoped_tool(root, run_id, run_info(root, run_id))
    assert result["state"] == "needs_review"
    assert canary.verify_canary(item["project_id"], item["plan_id"], root)["outcome"] != "passed_real_managed_worker"


def test_wrong_project_or_tampered_canary_marker_denied(scope):
    root, _parent = scope
    item = canary._prepare_canary(root)
    other = create_project(root, "Other owner project", "Do not use for canary")
    with pytest.raises(WorkStop):
        canary.verify_canary(other["id"], item["plan_id"], root)
    with db(root) as conn:
        conn.execute("UPDATE projects SET instructions=? WHERE id=?",
                     ("Untrusted tampered marker", item["project_id"]))
    with pytest.raises(WorkStop, match="Not the labeled"):
        canary.verify_canary(item["project_id"], item["plan_id"], root)
    

def test_invalid_ids_rejected_before_database_read(scope):
    root, _parent = scope
    with pytest.raises(WorkStop):
        canary.verify_canary("../../host", "0" * 32, root)
