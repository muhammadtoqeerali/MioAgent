"""SCORPIO9C4 real Work worker contract on isolated private test DBs only."""
from __future__ import annotations

import hashlib
import shutil

import pytest

from mio import scorpio9c4_worker_tool
from mio.scorpio9c3_step_grants import _stage, expected_prompt
from mio.scorpio9c4_worker_tool import maybe_execute_scoped_tool
from mio.supervisor_core import advance_supervisor, approve_plan, create_plan, pause_plan
from mio.work_core import WorkStop, create_project, create_run, db, run_info


@pytest.fixture
def scope(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    root = private / "work"
    project = create_project(root, "Worker tool test", "Offline approved step")
    base = private / "tool-inputs"
    base.mkdir(mode=0o700)
    folder = base / project["id"]
    folder.mkdir(mode=0o700)
    (folder / "sample.txt").write_bytes(b"scorpio isolated test fixture\n")
    name = "sample.txt"
    plan = create_plan(root, project["id"], "Compute approved bounded digest", [expected_prompt(name)])
    return root, project["id"], plan["id"], plan["steps"][0]["id"], folder


def queued(scope, *, stage=True):
    root, project, plan, step, _folder = scope
    item = _stage(root, project, plan, step, "sample.txt") if stage else None
    approve_plan(root, plan)
    run_id = advance_supervisor(root)
    assert run_id
    return run_id, item


def test_only_explicit_tool_run_intercepted(scope):
    root, project, _plan, _step, _folder = scope
    run = create_run(root, project, "Summarize this normal project task")
    assert maybe_execute_scoped_tool(root, run["id"], run_info(root, run["id"])) is None
    assert run_info(root, run["id"])["state"] == "queued"


def test_unbound_digest_prompt_never_falls_through_to_model(scope):
    root, _project, _plan, _step, _folder = scope
    run_id, _item = queued(scope, stage=False)
    result = maybe_execute_scoped_tool(root, run_id, run_info(root, run_id))
    assert result["state"] == "needs_review"
    assert result["mode"] == "tool_denied"
    assert result["result"] is None
    assert advance_supervisor(root) is None


def test_success_digest_updates_one_work_run_and_supervisor(scope, monkeypatch):
    root, _project, _plan, _step, folder = scope
    run_id, item = queued(scope)
    monkeypatch.setattr(scorpio9c4_worker_tool, "_sandbox_digest",
                        lambda fd: scorpio9c4_worker_tool._digest(fd))
    result = maybe_execute_scoped_tool(root, run_id, run_info(root, run_id))
    assert result["state"] == "answered"
    assert result["mode"] == "tool_sha256"
    assert result["result"] == "Verified offline SHA-256: " + hashlib.sha256(
        (folder / "sample.txt").read_bytes()).hexdigest()
    assert "tool.claimed" in [x["phase"] for x in result["events"]]
    assert "tool.verified" in [x["phase"] for x in result["events"]]
    with db(root) as conn:
        assert conn.execute("SELECT used FROM scorpio9c_grants WHERE id=?",
                            (item["grant_id"],)).fetchone()[0] == 1
    assert maybe_execute_scoped_tool(root, run_id, result)["state"] == "answered"
    assert advance_supervisor(root) is None


def test_sandbox_failure_consumes_and_halts(scope, monkeypatch):
    root, _project, _plan, _step, _folder = scope
    run_id, item = queued(scope)

    def blocked(_fd):
        raise WorkStop("sandbox unavailable")

    monkeypatch.setattr(scorpio9c4_worker_tool, "_sandbox_digest", blocked)
    result = maybe_execute_scoped_tool(root, run_id, run_info(root, run_id))
    assert result["state"] == "needs_review"
    assert "sandbox unavailable" not in str(result)
    assert advance_supervisor(root) is None
    with db(root) as conn:
        assert conn.execute("SELECT used FROM scorpio9c_grants WHERE id=?",
                            (item["grant_id"],)).fetchone()[0] == 1


def test_revoked_staged_grant_denied(scope, monkeypatch):
    root, _project, _plan, _step, _folder = scope
    run_id, item = queued(scope)
    with db(root) as conn:
        conn.execute("UPDATE scorpio9c_grants SET revoked=1 WHERE id=?", (item["grant_id"],))
    monkeypatch.setattr(scorpio9c4_worker_tool, "_sandbox_digest",
                        lambda _fd: pytest.fail("revoked grant reached bwrap"))
    assert maybe_execute_scoped_tool(root, run_id, run_info(root, run_id))["state"] == "needs_review"


def test_expired_staged_grant_denied(scope, monkeypatch):
    root, _project, _plan, _step, _folder = scope
    run_id, item = queued(scope)
    with db(root) as conn:
        conn.execute("UPDATE scorpio9c_grants SET expires=0 WHERE id=?", (item["grant_id"],))
    monkeypatch.setattr(scorpio9c4_worker_tool, "_sandbox_digest",
                        lambda _fd: pytest.fail("expired grant reached bwrap"))
    assert maybe_execute_scoped_tool(root, run_id, run_info(root, run_id))["state"] == "needs_review"


def test_input_changed_denied_before_spend(scope, monkeypatch):
    root, _project, _plan, _step, folder = scope
    run_id, item = queued(scope)
    (folder / "sample.txt").write_bytes(b"DIFFERENT DATA\n")
    monkeypatch.setattr(scorpio9c4_worker_tool, "_sandbox_digest",
                        lambda _fd: pytest.fail("modified file reached bwrap"))
    assert maybe_execute_scoped_tool(root, run_id, run_info(root, run_id))["state"] == "needs_review"
    with db(root) as conn:
        assert conn.execute("SELECT used FROM scorpio9c_grants WHERE id=?",
                            (item["grant_id"],)).fetchone()[0] == 0


def test_pause_before_claim_denied(scope):
    root, _project, plan, _step, _folder = scope
    run_id, _item = queued(scope)
    pause_plan(root, plan)
    assert maybe_execute_scoped_tool(root, run_id, run_info(root, run_id))["state"] == "needs_review"


def test_exact_run_prompt_must_match_staged_step(scope):
    root, _project, _plan, _step, _folder = scope
    run_id, _item = queued(scope)
    with db(root) as conn:
        conn.execute("UPDATE runs SET prompt='Changed by untrusted text' WHERE id=?", (run_id,))
    assert maybe_execute_scoped_tool(root, run_id, run_info(root, run_id))["state"] == "needs_review"


def test_cannot_spoof_run_mode(scope):
    root, _project, _plan, _step, _folder = scope
    run_id, _item = queued(scope)
    with db(root) as conn:
        conn.execute("UPDATE runs SET mode='engineering_queued' WHERE id=?", (run_id,))
    assert maybe_execute_scoped_tool(root, run_id, run_info(root, run_id))["state"] == "needs_review"



def test_bound_grant_cross_project_tampering_denied(scope, monkeypatch):
    root, _project, _plan, _step, _folder = scope
    run_id, item = queued(scope)
    other = create_project(root, "Other owner project", "Not authorized for this step")
    with db(root) as conn:
        conn.execute("UPDATE scorpio9c_step_bindings SET project=? WHERE grant_id=?",
                     (other["id"], item["grant_id"]))
    monkeypatch.setattr(scorpio9c4_worker_tool, "_sandbox_digest",
                        lambda _fd: pytest.fail("cross-project binding reached bwrap"))
    assert maybe_execute_scoped_tool(root, run_id, run_info(root, run_id))["state"] == "needs_review"


def test_owner_revocation_during_execution_blocks_answered(scope, monkeypatch):
    root, _project, _plan, _step, _folder = scope
    run_id, item = queued(scope)

    def revoke_midflight(fd):
        with db(root) as conn:
            conn.execute("UPDATE scorpio9c_grants SET revoked=1 WHERE id=?", (item["grant_id"],))
        return scorpio9c4_worker_tool._digest(fd)

    monkeypatch.setattr(scorpio9c4_worker_tool, "_sandbox_digest", revoke_midflight)
    assert maybe_execute_scoped_tool(root, run_id, run_info(root, run_id))["state"] == "needs_review"


def test_real_bwrap_file_digest(scope):
    if shutil.which("bwrap") is None:
        pytest.fail("bwrap mandatory for live tool worker")
    root, _project, _plan, _step, folder = scope
    run_id, _item = queued(scope)
    result = maybe_execute_scoped_tool(root, run_id, run_info(root, run_id))
    assert result["state"] == "answered", result
    assert result["result"].endswith(hashlib.sha256((folder / "sample.txt").read_bytes()).hexdigest())


def test_agent_source_integrates_without_changing_worker_scheduler():
    source = (__import__("pathlib").Path(__file__).resolve().parents[1] / "mio/work_agent.py").read_text()
    assert "maybe_execute_scoped_tool(root, run_id, record)" in source
    assert "return tool_result" in source
    worker = (__import__("pathlib").Path(__file__).resolve().parents[1] / "mio/work_worker.py").read_text()
    assert "advance_supervisor(root)" in worker
    assert "run_id = pending(root)" in worker
