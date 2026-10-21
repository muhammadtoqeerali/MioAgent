"""v0.4K peer-reviewed research search outage regression, no network in tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from mio import work_agent
from mio.scholarly_search import scholarly_search
from mio.studio_files import StudioError
from mio.work_core import create_project, create_run


def root(tmp_path: Path) -> Path:
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    return parent / "work"


class FakeFleet:
    def __init__(self, settings, role):
        self.role = role

    async def complete(self, messages, max_tokens):
        if self.role == "review":
            return SimpleNamespace(text="Use only cited evidence.", model="reviewer")
        return SimpleNamespace(text="A reported result exists [W1].", model="writer")


async def _mock_scholarly(query: str, payload: dict):
    def serve(request):
        assert request.url.host == "api.crossref.org"
        assert request.url.path == "/works"
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:
        return await scholarly_search(query, client)


def test_scholarly_provider_rejects_unrelated_sources_and_only_links_real_dois():
    data = {"message": {"items": [
        {"type": "journal-article", "title": ["Italian eighteenth birthday greetings"],
         "DOI": "10.1000/irrelevant", "container-title": ["Greetings"],
         "published": {"date-parts": [[2025]]}},
        {"type": "journal-article", "title": ["Humanoid Robot Manipulation Learning"],
         "DOI": "10.1000/humanoid.manipulation", "container-title": ["Robotics Journal"],
         "published": {"date-parts": [[2026]]},
         "abstract": "<jats:p>Robotic manipulation via learning.</jats:p>"},
    ]}}
    results = asyncio.run(_mock_scholarly("humanoid robot manipulation research", data))
    assert len(results) == 1
    assert results[0]["ref"] == "W1"
    assert results[0]["url"] == "https://doi.org/10.1000/humanoid.manipulation"
    assert "Deposited abstract excerpt" in results[0]["snippet"]


def test_scholarly_provider_never_accepts_unrelated_records():
    data = {"message": {"items": [
        {"type": "journal-article", "title": ["Italian eighteenth birthday greetings"],
         "DOI": "10.1000/irrelevant"},
    ]}}
    with pytest.raises(StudioError, match="no topic-relevant"):
        asyncio.run(_mock_scholarly("humanoid robot manipulation research", data))


def test_work_falls_back_to_scholarly_metadata_only_when_explicit(tmp_path, monkeypatch):
    base = root(tmp_path)
    project = create_project(base, "Robotics research", "")
    prompt = (
        "Search the web for recent peer-reviewed research on humanoid robot manipulation. "
        "Summarize two approaches and cite sources."
    )
    task = create_run(base, project["id"], prompt)
    monkeypatch.setattr(work_agent, "FleetRouter", FakeFleet)
    searches = AsyncMock(side_effect=StudioError("No topic-relevant sources"))
    scholarly = AsyncMock(return_value=[{
        "ref": "W1", "title": "Humanoid Robot Manipulation Learning",
        "url": "https://doi.org/10.1000/humanoid.manipulation",
        "snippet": "Crossref journal-article metadata; methods not verified",
    }])
    monkeypatch.setattr(work_agent, "web_search", searches)
    monkeypatch.setattr(work_agent, "scholarly_search", scholarly)
    monkeypatch.setattr(
        work_agent, "enrich_sources",
        AsyncMock(side_effect=lambda sources: [
            {**source, "page_verified": False,
             "evidence_scope": "Crossref metadata, not retrieved page"}
            for source in sources
        ]),
    )
    result = asyncio.run(work_agent.execute(base, task["id"], SimpleNamespace()))
    assert result["state"] == "needs_review"
    assert "evidence.check" in [e["phase"] for e in result["events"]]
    assert searches.await_count == 2
    scholarly.assert_awaited_once_with("humanoid robot manipulation research")
    assert "web.scholarly" in [event["phase"] for event in result["events"]]
    assert result["sources"][0]["url"].startswith("https://doi.org/")
