"""Work Core: persistent state, owner memory, source-only research and auth."""
from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from mio import work_agent, work_core
from mio.work_api import register_work_routes
from mio.work_core import (
    WorkStop,
    add_memory,
    create_project,
    create_run,
    event,
    interrupt_orphaned,
    project_info,
    projects,
    remove_memory,
    run_info,
    update,
)


def root(tmp_path: Path) -> Path:
    parent = tmp_path / "secure"
    parent.mkdir(mode=0o700, exist_ok=True)
    return parent / "work"


def test_projects_persist_and_memory_is_explicit(tmp_path):
    base = root(tmp_path)
    item = create_project(base, "Robotics Research", "Use cited sources")
    assert projects(base)[0]["id"] == item["id"]
    assert project_info(base, item["id"])["memories"] == []
    note = add_memory(base, item["id"], "Use IEEE reference format")
    assert project_info(base, item["id"])["memories"][0]["content"] == "Use IEEE reference format"
    remove_memory(base, item["id"], note["id"])
    assert project_info(base, item["id"])["memories"] == []
    assert (base / "work.db").stat().st_mode & 0o077 == 0


def test_project_isolation_and_max_memory(tmp_path):
    base = root(tmp_path)
    a = create_project(base, "Project A", "")
    b = create_project(base, "Project B", "")
    note = add_memory(base, a["id"], "Private instruction")
    with pytest.raises(WorkStop):
        remove_memory(base, b["id"], note["id"])
    assert project_info(base, b["id"])["memories"] == []


def test_run_is_durable_and_terminal_state_cannot_be_overwritten(tmp_path):
    base = root(tmp_path)
    project = create_project(base, "Alpha", "")
    first = create_run(base, project["id"], "Summarize robotics papers")
    with pytest.raises(WorkStop, match="One Work run"):
        create_run(base, project["id"], "Another task")
    event(base, first["id"], "research", "Search started")
    update(base, first["id"], "answered", mode="chat", result="Answer here")
    assert run_info(base, first["id"])["events"][-1]["phase"] == "research"
    assert run_info(base, first["id"])["result"] == "Answer here"
    with pytest.raises(WorkStop, match="terminal"):
        update(base, first["id"], "answered", result="Changed")
    create_run(base, project["id"], "A second new task")


def test_restart_marks_unfinished_not_completed(tmp_path):
    base = root(tmp_path)
    project = create_project(base, "Alpha", "")
    run = create_run(base, project["id"], "Research recent robotics")
    update(base, run["id"], "running", mode="research")
    interrupt_orphaned(base)
    assert run_info(base, run["id"])["state"] == "interrupted"


def test_invalid_identifiers_and_private_storage(tmp_path):
    base = root(tmp_path)
    project = create_project(base, "Alpha", "")
    for token in ["../invalid", "f" * 31, "z" * 32, "1" * 100]:
        with pytest.raises(WorkStop):
            project_info(base, token)
    base2 = tmp_path / "unsafe"
    base2.mkdir(mode=0o777)
    base2.chmod(0o755)
    with pytest.raises(WorkStop):
        create_project(base2 / "work", "Alpha", "")
    assert project_info(base, project["id"])["title"] == "Alpha"


def test_attached_files_are_only_owner_linked(tmp_path, monkeypatch):
    from mio.studio_files import save_attachment
    runtime = tmp_path / "sandbox"
    runtime.mkdir(mode=0o700)
    monkeypatch.setattr(work_core, "RUNTIME", runtime)
    project = create_project(root(tmp_path), "Docs", "")
    saved = save_attachment(runtime / "studio" / "attachments", "lab.txt", base64.b64encode(b"Experiment 42").decode())
    linked = work_core.link_file(root(tmp_path), project["id"], saved["id"])
    assert linked["name"] == "lab.txt"
    with pytest.raises(WorkStop, match="already linked"):
        work_core.link_file(root(tmp_path), project["id"], saved["id"])
    assert project_info(root(tmp_path), project["id"])["assets"][0]["name"] == "lab.txt"
    assert "Experiment 42" not in str(project_info(root(tmp_path), project["id"]))


class FakeFleet:
    def __init__(self, settings, role):
        self.role = role

    async def complete(self, messages, max_tokens):
        if self.role == "review":
            return SimpleNamespace(text="Use only cited evidence.", model="reviewer")
        return SimpleNamespace(text="A reported result exists [W1].", model="writer")


def test_real_execution_records_search_and_review(tmp_path, monkeypatch):
    base = root(tmp_path)
    project = create_project(base, "Research", "Only cite supplied evidence")
    run = create_run(base, project["id"], "Search the web for recent humanoid robotics papers")
    monkeypatch.setattr(work_agent, "FleetRouter", FakeFleet)
    search = AsyncMock(return_value=[{"ref":"W1", "title":"Humanoid study", "url":"https://example.edu/paper", "snippet":"Robotics evaluation"}])
    monkeypatch.setattr(work_agent, "web_search", search)
    monkeypatch.setattr(
        work_agent, "enrich_sources",
        AsyncMock(side_effect=lambda sources: [
            {**source, "page_verified": True,
             "page_excerpt": "Retrieved HTML page excerpt for this test"}
            for source in sources
        ]),
    )
    result = asyncio.run(work_agent.execute(base, run["id"], SimpleNamespace()))
    assert result["state"] == "answered"
    assert result["sources"][0]["page_verified"] is True
    assert "web.fetch" in [e["phase"] for e in result["events"]]
    assert result["mode"] == "research"
    assert result["sources"][0]["ref"] == "W1"
    assert "model.review" in [x["phase"] for x in result["events"]]
    search.assert_awaited_once()


def test_research_without_citations_is_needs_review(tmp_path, monkeypatch):
    base = root(tmp_path)
    project = create_project(base, "Research", "")
    run = create_run(base, project["id"], "Research latest robotics studies")
    class NoCites(FakeFleet):
        async def complete(self, messages, max_tokens):
            if self.role == "review":
                return SimpleNamespace(text="Add source citations.", model="reviewer")
            return SimpleNamespace(text="I found a result but cannot cite it.", model="writer")
    monkeypatch.setattr(work_agent, "FleetRouter", NoCites)
    monkeypatch.setattr(work_agent, "web_search", AsyncMock(return_value=[
        {"ref":"W1", "title":"Paper", "url":"https://example.edu/paper", "snippet":"Robotics"}]))
    result = asyncio.run(work_agent.execute(base, run["id"], SimpleNamespace()))
    assert result["state"] == "needs_review"


def test_failed_search_is_not_a_success(tmp_path, monkeypatch):
    base = root(tmp_path)
    project = create_project(base, "Research", "")
    run = create_run(base, project["id"], "Research latest robotics studies")
    monkeypatch.setattr(work_agent, "web_search", AsyncMock(side_effect=ValueError("No evidence")))
    result = asyncio.run(work_agent.execute(base, run["id"], SimpleNamespace()))
    assert result["state"] == "failed"
    assert result["result"] is None


def test_api_requires_auth_and_owner_approved_memory(tmp_path):
    base = root(tmp_path)
    app = FastAPI()

    def auth(authorization: str | None = Header(default=None)):
        if authorization != "Bearer test":
            raise HTTPException(401, detail="Unauthorized")

    register_work_routes(app, SimpleNamespace(), auth, base)
    with TestClient(app) as client:
        assert client.get("/api/work/overview").status_code == 401
        h = {"Authorization": "Bearer test"}
        overview = client.get("/api/work/overview", headers=h).json()
        assert overview["permissions"]["host_shell"] is False
        assert len(overview["skills"]) == 3
        created = client.post("/api/work/projects", headers=h, json={"title":"New Project","instructions":"Keep sources"})
        assert created.status_code == 201
        pid = created.json()["id"]
        assert client.post(f"/api/work/projects/{pid}/memory", headers=h,
                           json={"content":"Always cite the source","approved":False}).status_code == 422
        good = client.post(f"/api/work/projects/{pid}/memory", headers=h,
                           json={"content":"Always cite the source","approved":True})
        assert good.status_code == 201
        assert client.get(f"/api/work/projects/{pid}", headers=h).json()["memories"][0]["content"] == "Always cite the source"
        assert client.get(f"/api/work/runs/{'f'*32}", headers=h).status_code == 404


def test_work_research_search_retry_v04k(tmp_path, monkeypatch):
    from mio.studio_files import StudioError

    base = root(tmp_path)
    project = create_project(base, "Robotics", "")
    prompt = (
        "Search the web for recent peer-reviewed research on humanoid robot manipulation. "
        "Summarize two concrete approaches and cite only the retrieved [W1] to [W6] "
        "sources inline, noting that full pages were not verified."
    )
    run = create_run(base, project["id"], prompt)
    monkeypatch.setattr(work_agent, "FleetRouter", FakeFleet)
    search = AsyncMock(side_effect=[
        StudioError("No topic-relevant sources"),
        [{"ref": "W1", "title": "Humanoid robot manipulation",
          "url": "https://example.edu/study", "snippet": "Humanoid robotics research"}],
    ])
    monkeypatch.setattr(work_agent, "web_search", search)
    monkeypatch.setattr(
        work_agent, "enrich_sources",
        AsyncMock(side_effect=lambda sources: [
            {**source, "page_verified": True,
             "page_excerpt": "Retrieved HTML page excerpt for this test"}
            for source in sources
        ]),
    )
    result = asyncio.run(work_agent.execute(base, run["id"], SimpleNamespace()))
    assert result["state"] == "answered"
    assert result["sources"][0]["page_verified"] is True
    assert "web.fetch" in [e["phase"] for e in result["events"]]
    assert [call.args[0] for call in search.await_args_list] == [
        prompt, "humanoid robot manipulation research",
    ]
    assert "web.retry" in [e["phase"] for e in result["events"]]


def test_work_research_retry_bounded_v04k(tmp_path, monkeypatch):
    from mio.studio_files import StudioError

    base = root(tmp_path)
    project = create_project(base, "Robotics", "")
    run = create_run(base, project["id"],
                     "Search the web for robotics research. Summarize two sources.")
    search = AsyncMock(side_effect=StudioError("No topic-relevant sources"))
    monkeypatch.setattr(work_agent, "web_search", search)
    result = asyncio.run(work_agent.execute(base, run["id"], SimpleNamespace()))
    assert result["state"] == "failed"
    assert search.await_count == 2
    assert [e["phase"] for e in result["events"]].count("web.retry") == 1


def test_work_long_research_prompt_uses_bounded_search_query(
    tmp_path, monkeypatch,
):
    prompt = (
        "Search the web for the official Python 3 math module "
        "documentation for sqrt, sin, cos and log. "
        "Research what these functions do, their input "
        "requirements and relevant domain restrictions. "
        "Use actual retrieved public webpage excerpts when "
        "available and cite the associated [W1] to [W6] "
        "references accurately. Clearly state if a source "
        "could not be opened."
    )
    assert len(prompt) == 354

    base = root(tmp_path)
    project = create_project(base, "Long Query Regression", "")
    task = create_run(base, project["id"], prompt)

    monkeypatch.setattr(work_agent, "FleetRouter", FakeFleet)

    search = AsyncMock(return_value=[{
        "ref": "W1",
        "title": "Python math module documentation",
        "url": "https://docs.python.org/3/library/math.html",
        "snippet": "Python sqrt sin cos log math functions",
    }])

    monkeypatch.setattr(work_agent, "web_search", search)

    monkeypatch.setattr(
        work_agent, "enrich_sources",
        AsyncMock(side_effect=lambda sources: [
            {
                **source,
                "page_verified": True,
                "page_excerpt": "Verified public Python mathematical "
                                "documentation excerpt used in this test.",
            }
            for source in sources
        ]),
    )

    outcome = asyncio.run(
        work_agent.execute(base, task["id"], SimpleNamespace())
    )

    assert outcome["state"] == "answered"
    assert search.await_count == 1

    query = search.await_args.args[0]
    assert 3 <= len(query) <= 350
    assert "Python" in query
    assert "math" in query

    assert outcome["sources"][0]["page_verified"] is True
    assert "web.query" in [
        item["phase"] for item in outcome["events"]
    ]
    assert "web.fetch" in [
        item["phase"] for item in outcome["events"]
    ]
