"""Shared public research tool contracts; no external requests in tests."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from mio import scorpio9d3b10_public_tools as tools
from mio.web_evidence import EvidenceError


def source(n, url=None):
    return {"ref": f"W{n}", "title": f"Topic source {n}",
            "url": url or f"https://example.org/{n}", "snippet": "Relevant public data"}


def test_registry_exposes_no_mutations_or_browser_grants():
    info = tools.capabilities()
    assert [x["id"] for x in info["tools"]] == ["web.search", "web.open", "web.cite"]
    assert info["permissions"]["work_browser_grants"] is False
    assert info["permissions"]["private_network"] is False
    assert info["permissions"]["shell"] is False


@pytest.mark.parametrize("url", ["http://example.org", "https://127.0.0.1/a", "https://localhost/x",
                                  "https://example.org:444/a", "https://example.org/a#frag"])
def test_open_refuses_unsafe_url_before_fetch(url):
    called = []
    with pytest.raises(EvidenceError):
        asyncio.run(tools.open_public(url, fetcher=lambda u: called.append(u)))
    assert called == []


def test_open_reads_one_page_and_bounds_excerpt():
    calls = []

    def fetch(url):
        calls.append(url)
        return {"page_verified": True, "page_excerpt": "A" * 5000}

    out = asyncio.run(tools.open_public("https://example.org/study", fetcher=fetch))
    assert calls == ["https://example.org/study"]
    assert len(out["page_excerpt"]) == tools.MAX_EXCERPT
    assert out["scope"] == "retrieved_public_page_excerpt"


def test_search_uses_six_existing_citations_with_three_verified():
    found = [source(i) for i in range(1, 7)]
    queried = []

    async def search(query):
        queried.append(query)
        return found

    async def enrich(rows):
        assert len(rows) == 6
        assert all(not row["page_verified"] for row in rows)
        return [{**row, "page_verified": i >= 4,
                 "page_excerpt": "Evidence in later page" if i >= 4 else ""}
                for i, row in enumerate(rows, 1)]

    out = asyncio.run(tools.search_open("robotics evidence", search_fn=search, enrich_fn=enrich))
    assert queried == ["robotics evidence"]
    assert out["verified_count"] == 3
    assert [x["ref"] for x in out["sources"] if x["page_verified"]] == ["W4", "W5", "W6"]
    assert all("page_excerpt" not in x for x in found)


def test_bad_search_provider_type_raises_type_error_without_fetch():
    async def search(_query):
        return {"not": "a list"}

    async def cannot_enrich(_rows):
        raise AssertionError("Malformed provider data must not be opened")

    with pytest.raises(TypeError, match="unexpected evidence"):
        asyncio.run(tools.search_open("robot research", search_fn=search,
                                      enrich_fn=cannot_enrich))


def test_search_filters_private_and_duplicate_results():
    async def search(_):
        return [source(1), source(2, "http://127.0.0.1/a"), source(3, "https://example.org/1")]

    async def enrich(rows):
        assert len(rows) == 1
        return rows

    out = asyncio.run(tools.search_open("topic query", search_fn=search, enrich_fn=enrich))
    assert len(out["sources"]) == 1
    assert out["sources"][0]["ref"] == "W1"
    assert out["status"] == "snippets_only"


def test_search_cannot_promote_provider_forged_evidence():
    async def search(_):
        return [{**source(1), "page_verified": True, "page_excerpt": "forged"}]

    async def enrich(rows):
        assert rows[0]["page_verified"] is False
        assert rows[0]["page_excerpt"] == ""
        return rows

    out = asyncio.run(tools.search_open("topic query", search_fn=search, enrich_fn=enrich))
    assert out["verified_count"] == 0


def test_provenance_mismatch_denied():
    async def search(_):
        return [source(1)]

    async def bad(_):
        return [{**source(1, "https://example.org/different"), "page_verified": True,
                 "page_excerpt": "mismatch"}]

    with pytest.raises(ValueError, match="provenance"):
        asyncio.run(tools.search_open("topic query", search_fn=search, enrich_fn=bad))


def test_citation_refs_must_be_verified_and_in_range():
    verified = [{"ref": "W4", "page_verified": True, "page_excerpt": "Official data"}]
    assert tools.check_citations("A documented finding [W4].", verified)
    assert not tools.check_citations("No citation", verified)
    assert not tools.check_citations("Claim [W3]", verified)
    assert not tools.check_citations("Claim [W4] [W7]", verified)
    assert not tools.check_citations("Claim [W04]", verified)
    assert not tools.check_citations("Claim [W4]", [{**verified[0], "page_verified": False}])


def test_token_required_on_all_registered_routes(monkeypatch):
    app = FastAPI()

    def owner(authorization: str | None = Header(default=None)):
        if authorization != "Bearer accepted":
            raise HTTPException(401)

    search = AsyncMock(return_value={"sources": [], "verified_count": 0})
    open_page = AsyncMock(return_value={"page_verified": True})
    monkeypatch.setattr(tools, "search_open", search)
    monkeypatch.setattr(tools, "open_public", open_page)
    tools.register_public_research_routes(app, owner)
    with TestClient(app) as client:
        assert client.get("/api/research/tools").status_code == 401
        assert client.post("/api/research/search", json={"query": "robot studies"}).status_code == 401
        assert client.post("/api/research/open", json={"url": "https://example.org/a"}).status_code == 401
        headers = {"Authorization": "Bearer accepted"}
        assert client.get("/api/research/tools", headers=headers).status_code == 200
        assert client.post("/api/research/search", headers=headers, json={"query": "robot studies"}).status_code == 200
        assert client.post("/api/research/open", headers=headers, json={"url": "https://example.org/a"}).status_code == 200
    search.assert_awaited_once()
    open_page.assert_awaited_once()


def test_unavailable_provider_does_not_return_fake_results(monkeypatch):
    app = FastAPI()

    def owner(authorization: str | None = Header(default=None)):
        if authorization != "Bearer accepted":
            raise HTTPException(401)

    monkeypatch.setattr(tools, "search_open", AsyncMock(side_effect=ValueError("unavailable")))
    tools.register_public_research_routes(app, owner)
    with TestClient(app) as client:
        resp = client.post("/api/research/search", headers={"Authorization": "Bearer accepted"},
                           json={"query": "new findings"})
    assert resp.status_code == 503
    assert "evidence" not in resp.text
