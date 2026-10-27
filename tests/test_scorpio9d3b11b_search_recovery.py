"""B11B: bounded provider recovery and honest no-evidence responses."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from mio import studio_api
from mio.scorpio9d3b11a_studio_evidence import studio_research_sources
from mio.studio_files import StudioError
from mio.studio_search_quality import quality_search, search_query


def record():
    return {"title": "European Space Agency Hera mission scientific objectives",
            "snippet": "The ESA Hera mission scientifically investigates an asteroid and its orbit.",
            "url": "https://www.esa.int/Science_Exploration/Space_Science/Hera"}


def run(coro):
    return asyncio.run(coro)


def test_instruction_cleanup_preserves_real_topic():
    query = search_query(
        "According to public sources, what are the European Space Agency Hera "
        "mission's scientific objectives? Cite the relevant evidence."
    )
    assert query == "what are the European Space Agency Hera mission's scientific objectives"
    assert "Cite" not in query and "According to" not in query


def test_compact_second_retry_uses_independent_provider():
    seen = []

    async def first(query, client):
        seen.append(("first", query))
        if query == "european space agency hera mission":
            raise StudioError("First provider temporarily unavailable")
        return []

    async def second(query, client):
        seen.append(("second", query))
        if query == "european space agency hera mission":
            return [record()]
        return []

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: pytest.fail("No network requests allowed"))) as client:
            return await quality_search(
                "According to public sources, what are the European Space Agency Hera "
                "mission's scientific objectives? Cite the relevant evidence.",
                client, first, second,
            )
    result = run(exercise())
    assert len(result) == 1
    assert result[0]["url"].startswith("https://www.esa.int/")
    assert ("second", "european space agency hera mission") in seen
    assert len(seen) <= 7


def test_no_unrelated_results_admitted_even_after_retries():
    async def off_topic(query, client):
        return [{"title": "Generic Search", "snippet": "Search the internet for everything",
                 "url": "https://www.google.com/"}]

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: pytest.fail("No network requests allowed"))) as client:
            with pytest.raises(StudioError, match="no topic-relevant sources"):
                await quality_search("European Space Agency Hera scientific objectives",
                                     client, off_topic, off_topic)
    run(exercise())


def test_studio_research_empty_on_search_unavailable():
    async def unavailable(query):
        raise StudioError("Search providers returned no topic-relevant sources")

    result = run(studio_research_sources(
        "According to public sources, what are the European Space Agency Hera "
        "mission's scientific objectives? Cite the relevant evidence.", unavailable))
    assert result == []


def test_studio_does_not_swallow_malformed_search_shape():
    async def malformed(query):
        return {"invalid": "not list"}

    with pytest.raises(TypeError, match="list"):
        run(studio_research_sources("Latest public research on robotics", malformed))


def make_app(tmp_path, monkeypatch, *, sources):
    def owner(authorization: str | None = Header(default=None)):
        if authorization != "Bearer testcase":
            raise HTTPException(401)

    async def lookup(*args, **kwargs):
        return sources

    class NoModel:
        def __init__(self, *args):
            raise AssertionError("No local model must be called without verified evidence")

    monkeypatch.setattr(studio_api, "studio_research_sources", lookup)
    monkeypatch.setattr(studio_api, "FleetRouter", NoModel)
    app = FastAPI()
    studio_api.register_studio_routes(app, object(), owner, tmp_path)
    return app


def test_studio_no_relevant_results_returns_200_without_model(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch, sources=[])
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer testcase"}
        response = client.post("/api/studio/respond", headers=headers,
                               json={"mode": "research", "prompt": "Latest ESA mission research"})
    assert response.status_code == 200
    data = response.json()
    assert data["operation"] == "answer" and data["mode"] == "research"
    assert data["model"] is None and data["sources"] == []
    assert "not return usable topic-relevant evidence" in data["answer"]
    assert "No online search used" not in data["source_scope"]


def test_studio_snippet_only_returns_uncited_uncertain_answer(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch, sources=[{
        "ref": "W1", "title": "Public topic", "url": "https://example.org/news",
        "snippet": "Sample", "page_verified": False, "page_excerpt": "",
    }])
    with TestClient(app) as client:
        response = client.post("/api/studio/respond", headers={"Authorization": "Bearer testcase"},
                               json={"mode": "research", "prompt": "Latest mission research"})
    assert response.status_code == 200
    data = response.json()
    assert data["model"] is None
    assert data["sources"][0]["ref"] == "W1"
    assert "none yielded a readable" in data["answer"]
    assert "[W1]" not in data["answer"]


def test_studio_rejects_unauthenticated_research(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch, sources=[])
    with TestClient(app) as client:
        response = client.post("/api/studio/respond", json={"mode": "research", "prompt": "Latest research"})
    assert response.status_code == 401
