"""Regression: a HTTP-200 result is not necessarily relevant research evidence."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from mio.studio_files import StudioError
from mio.studio_search_quality import (
    focus_terms,
    quality_search,
    relevant_results,
    search_query,
)
from mio.studio_tools import web_search


def _record(title: str, url: str, snippet: str) -> dict:
    return {"ref": "W1", "title": title, "url": url, "snippet": snippet}


def test_human_instruction_becomes_topic_query():
    query = search_query(
        "Search the web for recent humanoid robotics research and give me three cited findings."
    )
    assert query == "recent humanoid robotics research"
    assert focus_terms(query) == ("humanoid", "robot", "research")


def test_no_fabricated_topic_matches():
    query = "recent humanoid robotics research"
    bad = [
        _record("Google", "https://www.google.com/xhtml/search", "Search the world's information"),
        _record("Bing Search", "https://www.bing.com", "Search the web with Bing"),
        _record("Generic news", "https://example.com/news", "Today's general world news"),
    ]
    assert relevant_results(bad, query) == []


def test_real_sources_are_ranked_and_deduplicated():
    query = "humanoid robotics research"
    samples = [
        _record("Research portal", "https://search.yahoo.com", "robot research"),
        _record("Humanoid robot advances", "https://robotics.example.edu/paper", "Research on humanoid robot locomotion"),
        _record("Robotics research", "https://example.org/study", "Humanoid robots in factories"),
        _record("Robotics research", "https://example.org/study", "Duplicate"),
    ]
    chosen = relevant_results(samples, query)
    assert len(chosen) == 2
    assert [x["ref"] for x in chosen] == ["W1", "W2"]
    assert all("search.yahoo" not in x["url"] for x in chosen)


def test_fallback_is_tried_if_bing_returns_irrelevant():
    calls = []

    async def primary(query: str, client: httpx.AsyncClient) -> list[dict]:
        calls.append(("primary", query))
        return [_record("Google Search", "https://www.google.com", "Search online")]

    async def fallback(query: str, client: httpx.AsyncClient) -> list[dict]:
        calls.append(("fallback", query))
        return [_record("Humanoid research", "https://example.org/humanoids", "Robotics advances in humanoid locomotion")]

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: pytest.fail("No network"))) as client:
            return await quality_search(
                "Search the web for recent humanoid robotics research and give me three cited findings.",
                client, primary, fallback,
            )

    result = asyncio.run(go())
    assert len(result) == 1
    assert result[0]["url"] == "https://example.org/humanoids"
    assert calls == [("primary", "recent humanoid robotics research"),
                     ("fallback", "recent humanoid robotics research")]


def test_both_providers_return_irrelevant_then_error():
    async def generic(query: str, client: httpx.AsyncClient) -> list[dict]:
        return [_record("Google", "https://www.google.com", "Search results")]

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: pytest.fail("No network"))) as client:
            with pytest.raises(StudioError, match="no topic-relevant sources"):
                await quality_search("robotics research", client, generic, generic)

    asyncio.run(go())


def test_legacy_rss_mock_behavior_preserved():
    xml = (b'<?xml version="1.0"?><rss><channel>'
           b'<item><title>Research news</title><link>https://example.org/paper</link>'
           b'<description>New dataset</description></item></channel></rss>')
    urls = []

    def provider(request):
        urls.append(str(request.url))
        return httpx.Response(200, content=xml)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            return await web_search("robot research", client)

    result = asyncio.run(go())
    assert result[0]["title"] == "Research news"
    assert "robot%20research" in urls[0]
    assert len(urls) == 1  # A relevant result satisfies an uncounted query
