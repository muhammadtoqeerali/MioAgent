"""SCORPIO9C2: bounded, non-mutating tool/grant inspection safety contracts."""
import os
import sqlite3

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from mio.scorpio9c_observe import grant_inventory, tool_catalog
from mio.scorpio9c_observe_api import register_scorpio9c_observe_routes
from mio.scorpio9c_tools import _create_grant
from mio.supervisor_core import approve_plan, create_plan, pause_plan
from mio.work_core import WorkStop, create_project, db


@pytest.fixture
def project_store(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    root = private / "work"
    project = create_project(root, "Read only inventory", "Owner-only offline scope")
    plan = create_plan(root, project["id"], "Inspect an owner-approved file", [
        "Read only the vetted sample file",
    ])
    approve_plan(root, plan["id"])
    base = private / "tool-inputs"
    base.mkdir(mode=0o700)
    folder = base / project["id"]
    folder.mkdir(mode=0o700)
    (folder / "sample.txt").write_text("fixture only", encoding="utf-8")
    return root, project["id"], plan["id"]


def _client(root):
    app = FastAPI()

    def require_owner(authorization: str | None = Header(default=None)):
        if authorization != "Bearer fake-local-test-token":
            raise HTTPException(401, detail="Unauthorized")

    register_scorpio9c_observe_routes(app, require_owner, root=root)
    return TestClient(app)


def test_catalog_is_disabled_and_not_a_grant():
    value = tool_catalog()
    assert value["tools"][0]["id"] == "workspace.sha256.v1"
    assert value["tools"][0]["network"] is False
    assert value["worker_execution"] == "disabled"
    assert value["grants_api"] == "read_only"
    assert value["grant_creation"] == "owner_console_only"
    assert value["external_skills"] == "disabled"


def test_private_empty_store_read_has_no_ddl(project_store):
    root, _, _ = project_store
    with db(root) as conn:
        tables_before = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    value = grant_inventory(root)
    with db(root) as conn:
        tables_after = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert tables_before == tables_after
    assert value["grants"] == [] and value["events"] == []
    assert value["can_grant_from_api"] is False


def test_active_grant_sanitized_and_scoped(project_store):
    root, project, plan = project_store
    item = _create_grant(root, project, plan, "sample.txt")
    value = grant_inventory(root)
    assert value["count"] == 1
    assert value["grants"][0]["id"] == item["id"]
    assert value["grants"][0]["state"] == "available_console_only"
    assert value["events"][0]["kind"] == "issued.local_console"
    assert "resource_dir" not in str(value)
    assert "expected_sha" not in str(value)
    assert str(root.parent) not in str(value)


def test_paused_consumed_revoked_expired_denied_in_inventory(project_store):
    root, project, plan = project_store
    issued = _create_grant(root, project, plan, "sample.txt")
    with db(root) as conn:
        conn.execute("UPDATE scorpio9c_grants SET used=1 WHERE id=?", (issued["id"],))
    assert grant_inventory(root)["grants"][0]["state"] == "consumed"
    with db(root) as conn:
        conn.execute("UPDATE scorpio9c_grants SET revoked=1 WHERE id=?", (issued["id"],))
    assert grant_inventory(root)["grants"][0]["state"] == "revoked"
    with db(root) as conn:
        conn.execute("UPDATE scorpio9c_grants SET used=0,revoked=0,expires=0 WHERE id=?",
                     (issued["id"],))
    assert grant_inventory(root)["grants"][0]["state"] == "expired"
    with db(root) as conn:
        conn.execute("UPDATE scorpio9c_grants SET expires=9999999999 WHERE id=?",
                     (issued["id"],))
    pause_plan(root, plan)
    assert grant_inventory(root)["grants"][0]["state"] == "inactive_plan"


def test_missing_or_untrusted_db_fail_closed(tmp_path, project_store):
    root, _, _ = project_store
    root_lookalike = tmp_path / "not-existing" / "work"
    with pytest.raises(WorkStop):
        grant_inventory(root_lookalike)
    sibling = root.parent / "link-work"
    sibling.symlink_to(root, target_is_directory=True)
    with pytest.raises(WorkStop):
        grant_inventory(sibling)
    if os.getuid() != 0:
        original = root.stat().st_mode & 0o777
        root.chmod(0o755)
        with pytest.raises(WorkStop):
            grant_inventory(root)
        root.chmod(original)


def test_api_auth_and_no_mutation_route(project_store):
    root, _, _ = project_store
    client = _client(root)
    assert client.get("/api/tools/registry").status_code == 401
    assert client.get("/api/tools/grants").status_code == 401
    head = {"Authorization": "Bearer fake-local-test-token"}
    a = client.get("/api/tools/registry", headers=head)
    b = client.get("/api/tools/grants", headers=head)
    assert a.status_code == 200 and b.status_code == 200
    assert a.json()["grant_creation"] == "owner_console_only"
    assert b.json()["grants"] == []
    assert client.post("/api/tools/grants", headers=head, json={"approved": True}).status_code == 405
    assert client.delete("/api/tools/grants", headers=head).status_code == 405


def test_api_private_store_failure_is_generic(project_store):
    root, _, _ = project_store
    (root / "work.db").rename(root / "work.db.backup")
    resp = _client(root).get("/api/tools/grants", headers={
        "Authorization": "Bearer fake-local-test-token"})
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Private tool grant inventory unavailable"


def test_sqlite_readonly_query_only(project_store):
    from mio.scorpio9c_observe import _readonly_db

    root, _, _ = project_store
    conn = _readonly_db(root)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("CREATE TABLE should_never_exist (x INTEGER)")
    finally:
        conn.close()


def test_registered_only_via_main_api():
    from pathlib import Path

    api = (Path(__file__).resolve().parents[1] / "mio/api.py").read_text()
    assert "from mio.scorpio9c_observe_api import register_scorpio9c_observe_routes" in api
    assert "register_scorpio9c_observe_routes(app, require_token)" in api
