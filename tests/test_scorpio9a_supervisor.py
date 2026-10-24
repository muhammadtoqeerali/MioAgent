"""Durable Scorpio9A supervisor safety and end-to-end SQLite dispatch contracts."""
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from mio.supervisor_api import register_supervisor_routes
from mio.supervisor_core import (
    advance_supervisor,
    approve_plan,
    create_plan,
    list_plans,
    pause_plan,
    read_plan,
)
from mio.work_core import WorkStop, create_project, db, run_info, update

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def work_root(tmp_path):
    parent = tmp_path / "private-runtime"
    parent.mkdir(mode=0o700)
    return parent / "work"


@pytest.fixture
def project(work_root):
    return create_project(work_root, "Supervisor research", "Owner controlled sequential tasks")


def _plan(root, project_id, steps=None):
    return create_plan(root, project_id, "Research two independent aspects of the topic", steps or [
        "Research the first dimension with sources", "Summarize the second dimension with evidence",
    ])


def test_draft_has_no_queued_work(work_root, project):
    draft = _plan(work_root, project["id"])
    assert draft["state"] == "draft"
    assert advance_supervisor(work_root) is None
    with db(work_root) as conn:
        assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_approved_plan_sequentially_dispatches_and_finishes(work_root, project):
    plan = _plan(work_root, project["id"])
    approve_plan(work_root, plan["id"])
    first = advance_supervisor(work_root)
    assert first and run_info(work_root, first)["mode"] == "pending"
    assert advance_supervisor(work_root) is None
    update(work_root, first, "answered", result="First result")
    second = advance_supervisor(work_root)
    assert second and second != first
    assert read_plan(work_root, plan["id"])["steps"][0]["state"] == "done"
    update(work_root, second, "answered", result="Second result")
    assert advance_supervisor(work_root) is None
    completed = read_plan(work_root, plan["id"])
    assert completed["state"] == "complete"
    assert all(x["state"] == "done" for x in completed["steps"])
    assert [x["phase"] for x in completed["events"]].count("step.queued") == 2


@pytest.mark.parametrize("state", ["needs_review", "interrupted", "failed"])
def test_non_success_halts_without_retry(work_root, project, state):
    plan = _plan(work_root, project["id"])
    approve_plan(work_root, plan["id"])
    first = advance_supervisor(work_root)
    update(work_root, first, state, error="Owner decision required")
    assert advance_supervisor(work_root) is None
    assert advance_supervisor(work_root) is None
    assert read_plan(work_root, plan["id"])["state"] == "attention"
    with db(work_root) as conn:
        assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 1


def test_pause_does_not_cancel_in_progress_run(work_root, project):
    plan = _plan(work_root, project["id"])
    approve_plan(work_root, plan["id"])
    first = advance_supervisor(work_root)
    pause_plan(work_root, plan["id"])
    update(work_root, first, "answered", result="Finished while paused")
    assert advance_supervisor(work_root) is None
    assert run_info(work_root, first)["state"] == "answered"
    assert read_plan(work_root, plan["id"])["state"] == "paused"
    approve_plan(work_root, plan["id"])
    second = advance_supervisor(work_root)
    assert second != first


def test_owner_work_queue_blocks_supervisor_dispatch(work_root, project):
    from mio.work_core import create_run
    plan = _plan(work_root, project["id"])
    approve_plan(work_root, plan["id"])
    ordinary = create_run(work_root, project["id"], "A direct owner task in progress")
    assert advance_supervisor(work_root) is None
    update(work_root, ordinary["id"], "answered", result="Normal Work done")
    assert advance_supervisor(work_root)


def test_second_plan_requires_first_to_finish(work_root, project):
    one = _plan(work_root, project["id"])
    two = _plan(work_root, project["id"])
    approve_plan(work_root, one["id"])
    with pytest.raises(WorkStop, match="Only one approved"):
        approve_plan(work_root, two["id"])


def test_archived_project_cannot_dispatch(work_root, project):
    plan = _plan(work_root, project["id"])
    approve_plan(work_root, plan["id"])
    from mio.work_lifecycle import archive_project
    archive_project(work_root, project["id"], archive=True)
    assert advance_supervisor(work_root) is None
    assert read_plan(work_root, plan["id"])["state"] == "attention"


def test_invalid_steps_and_project_refused(work_root, project):
    with pytest.raises(WorkStop):
        create_plan(work_root, project["id"], "Some meaningful goal", ["short"])
    with pytest.raises(WorkStop):
        _plan(work_root, "0" * 32)
    with pytest.raises(WorkStop):
        create_plan(work_root, project["id"], "Some meaningful goal", ["Valid test task"] * 7)


def test_authenticated_supervisor_api_no_implicit_approval(work_root, project):
    app = FastAPI()
    def require_token():
        raise HTTPException(401, "Unauthorized")
    register_supervisor_routes(app, require_token, root=work_root)
    client = TestClient(app)
    assert client.get("/api/supervisor/plans").status_code == 401
    assert client.post("/api/supervisor/plans", json={"project_id": project["id"],
                        "goal": "Some valid goal", "steps": ["An approved bounded step"]}).status_code == 401
    assert client.post("/api/supervisor/plans/" + "0" * 32 + "/approve",
                       json={"approved": True}).status_code == 401


def test_false_owner_approval_rejected_by_schema(work_root, project):
    app = FastAPI()
    register_supervisor_routes(app, lambda: None, root=work_root)
    client = TestClient(app)
    draft = client.post("/api/supervisor/plans", json={"project_id": project["id"],
                        "goal": "A valid bounded research goal", "steps": ["Research one topic carefully"]})
    assert draft.status_code == 201, draft.text
    id_ = draft.json()["id"]
    assert client.post(f"/api/supervisor/plans/{id_}/approve", json={"approved": False}).status_code == 422
    assert client.get(f"/api/supervisor/plans/{id_}").json()["state"] == "draft"
    assert client.post(f"/api/supervisor/plans/{id_}/approve", json={"approved": True}).status_code == 200


def test_source_integrated_into_worker_and_api():
    worker = (ROOT / "mio/work_worker.py").read_text()
    api = (ROOT / "mio/api.py").read_text()
    shell = (ROOT / "apps/dashboard/app/_mio/scorpio8a-shell.tsx").read_text()
    page = (ROOT / "apps/dashboard/app/supervisor/page.tsx").read_text()
    assert "advance_supervisor(root)" in worker and "run_id = pending(root)" in worker
    assert "register_supervisor_routes(app, require_token)" in api
    assert 'url:"/supervisor"' in shell
    assert "approved:true" in page and "Pause future steps" in page
    assert "mioApi<Plan>" in page and "supervisor/plans" in page


def test_plan_persists_across_reopened_sqlite(work_root, project):
    draft = _plan(work_root, project["id"])
    assert list_plans(work_root)["plans"][0]["id"] == draft["id"]
    assert read_plan(work_root, draft["id"])["steps"][1]["prompt"].startswith("Summarize")
