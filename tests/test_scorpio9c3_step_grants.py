"""SCORPIO9C3: task-specific staged grants without implicit worker permission."""
from __future__ import annotations

import os

import pytest

from mio.scorpio9c3_step_grants import _stage, bindings, check_queued_step, expected_prompt, stage
from mio.scorpio9c_tools import inspect, revoke
from mio.supervisor_core import advance_supervisor, approve_plan, create_plan, pause_plan
from mio.work_core import WorkStop, create_project, db


@pytest.fixture
def scope(tmp_path):
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    root = parent / "work"
    project = create_project(root, "Grant isolation", "No automatic tool use")
    prompt = expected_prompt("sample.txt")
    plan = create_plan(root, project["id"], "Inspect approved owner input", [prompt])
    folder = parent / "tool-inputs" / project["id"]
    folder.parent.mkdir(mode=0o700)
    folder.mkdir(mode=0o700)
    (folder / "sample.txt").write_text("nonsecret fixture\n", encoding="utf-8")
    return root, project["id"], plan["id"], plan["steps"][0]["id"], folder


def test_staging_requires_owner_tty(scope, monkeypatch):
    root, project, plan, step, _ = scope
    monkeypatch.setattr(os, "isatty", lambda _fd: False)
    with pytest.raises(WorkStop, match="interactive owner terminal"):
        stage(root, project, plan, step, "sample.txt")


def test_staging_requires_draft_exact_step_prompt(scope):
    root, project, plan, step, _ = scope
    with pytest.raises(WorkStop, match="Exact draft"):
        _stage(root, project, plan, "f" * 32, "sample.txt")
    with pytest.raises((WorkStop, FileNotFoundError)):
        _stage(root, project, plan, step, "other.txt")
    with pytest.raises(WorkStop, match="duration"):
        _stage(root, project, plan, step, "sample.txt", minutes=99)
    approve_plan(root, plan)
    with pytest.raises(WorkStop, match="Exact draft"):
        _stage(root, project, plan, step, "sample.txt")


def test_staged_grant_cannot_execute_before_separate_plan_approval(scope):
    root, project, plan, step, _ = scope
    issued = _stage(root, project, plan, step, "sample.txt")
    assert issued["worker_execution"] == "disabled"
    assert bindings(root)["bindings"][0]["status"] == "awaiting_plan_approval"
    with pytest.raises(WorkStop, match="owner-approved active plan"):
        inspect(root, issued["grant_id"], "sample.txt")


def test_preapproved_step_binding_maps_to_real_queued_run(scope):
    root, project, plan, step, _ = scope
    grant = _stage(root, project, plan, step, "sample.txt")
    approve_plan(root, plan)
    run_id = advance_supervisor(root)
    result = check_queued_step(root, run_id)
    assert result["grant"] == grant["grant_id"]
    assert result["worker_execution"] == "disabled"
    assert result["metadata_precheck"] == "passed"
    assert result["input_integrity"] == "not_verified"


def test_wrong_project_plan_or_step_denied(scope):
    root, project, plan, step, _ = scope
    with pytest.raises((WorkStop, FileNotFoundError)):
        _stage(root, "f" * 32, plan, step, "sample.txt")
    with pytest.raises(WorkStop):
        _stage(root, project, "f" * 32, step, "sample.txt")
    with pytest.raises(WorkStop):
        _stage(root, project, plan, "f" * 32, "sample.txt")
    with pytest.raises(WorkStop):
        check_queued_step(root, "f" * 32)


def test_single_step_cannot_have_two_staged_grants(scope):
    root, project, plan, step, _ = scope
    _stage(root, project, plan, step, "sample.txt")
    with pytest.raises(WorkStop, match="already has"):
        _stage(root, project, plan, step, "sample.txt")


def test_revocation_and_pause_invalidate_policy(scope, monkeypatch):
    root, project, plan, step, _ = scope
    issued = _stage(root, project, plan, step, "sample.txt")
    approve_plan(root, plan)
    run = advance_supervisor(root)
    monkeypatch.setattr(os, "isatty", lambda _fd: True)
    revoke(root, issued["grant_id"])
    with pytest.raises(WorkStop, match="policy"):
        check_queued_step(root, run)
    assert bindings(root)["bindings"][0]["status"] == "revoked"
    pause_plan(root, plan)
    with pytest.raises(WorkStop, match="policy"):
        check_queued_step(root, run)


def test_no_db_created_by_inventory_or_preview(tmp_path):
    root = tmp_path / "nonexistent-work"
    with pytest.raises(WorkStop):
        bindings(root)
    with pytest.raises(WorkStop):
        check_queued_step(root, "f" * 32)
    assert not root.exists()


def test_no_secret_contents_or_digest_in_inventory(scope):
    root, project, plan, step, _ = scope
    _stage(root, project, plan, step, "sample.txt")
    values = bindings(root)
    assert "nonsecret fixture" not in str(values)
    assert "resource_dir" not in str(values)
    assert values["bindings"][0]["project"] == project
    with db(root) as conn:
        assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_expired_grant_rejected_even_for_approved_queued_step(scope):
    root, project, plan, step, _ = scope
    issued = _stage(root, project, plan, step, "sample.txt")
    approve_plan(root, plan)
    run = advance_supervisor(root)
    with db(root) as conn:
        conn.execute("UPDATE scorpio9c_grants SET expires=1 WHERE id=?", (issued["grant_id"],))
    with pytest.raises(WorkStop, match="policy"):
        check_queued_step(root, run)
    assert bindings(root)["bindings"][0]["status"] == "expired"


def test_worker_mode_downgrade_denies_grant(scope):
    root, project, plan, step, _ = scope
    _stage(root, project, plan, step, "sample.txt")
    approve_plan(root, plan)
    run = advance_supervisor(root)
    with db(root) as conn:
        conn.execute("UPDATE runs SET mode='planning' WHERE id=?", (run,))
    with pytest.raises(WorkStop, match="policy"):
        check_queued_step(root, run)
