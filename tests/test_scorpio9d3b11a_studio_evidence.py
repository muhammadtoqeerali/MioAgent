"""B11A: Studio uses true public excerpts; snippets are never promoted to citations."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from mio import scorpio9d3b11a_studio_evidence as research


def record(title="Robotics experiment", url="https://example.org/robotics", snippet="Robotics research published"):
    return {"ref": "W1", "title": title, "url": url, "snippet": snippet}


def verified(rows):
    return [{**x, "page_verified": True,
             "page_excerpt": "A public robotics experiment evaluated control accuracy."} for x in rows]


def test_reads_public_excerpt_via_shared_b10(monkeypatch):
    from mio import scorpio9d3b10_public_tools as b10

    search = AsyncMock(return_value=[record()])
    enricher = AsyncMock(side_effect=verified)
    monkeypatch.setattr(b10, "enrich_sources", enricher)
    rows = asyncio.run(research.studio_research_sources("recent robotics research", search))
    assert search.await_count == 1
    assert enricher.await_count == 1
    assert rows[0]["page_verified"] is True
    assert rows[0]["scope"] == "retrieved_public_page_excerpt"
    context = research.studio_evidence_context(rows)
    assert "public robotics experiment" in context
    assert "UNTRUSTED DATA" in context
    assert research.checked_studio_answer("The experiment evaluated control accuracy [W1].", rows).startswith("The experiment")


def test_unverified_snippet_cannot_be_model_evidence():
    rows = [{**record(), "page_verified": False, "page_excerpt": ""}]
    assert research.studio_evidence_context(rows) == ""
    assert "snippets" in research.studio_source_scope(rows).lower()
    assert "snippets alone" in research.checked_studio_answer("Unproven fact [W1].", rows)


@pytest.mark.parametrize("answer", [
    "An unreferenced finding", "A claim [W7].", "A claim [W1] [W4].", "", "A claim [W01].",
])
def test_invalid_source_reference_is_rejected(answer):
    rows = [{**record(), "page_verified": True, "page_excerpt": "Test finding verified on webpage"}]
    assert "did not produce" in research.checked_studio_answer(answer, rows)


def test_snippet_not_sent_to_model_even_when_provider_forges_verification():
    rows = [{**record(), "page_verified": False, "page_excerpt": "Fake provider verified excerpt"}]
    assert research.studio_evidence_context(rows) == ""


def test_only_verified_source_excerpts_enter_prompt():
    rows = [
        {**record(), "page_verified": True, "page_excerpt": "Measured control accuracy in 2025."},
        {**record(title="Other source", url="https://example.com/other"),
         "ref": "W2", "page_verified": False, "page_excerpt": "UNVERIFIED FACT"},
    ]
    context = research.studio_evidence_context(rows)
    assert "Measured control accuracy" in context
    assert "UNVERIFIED FACT" not in context
    assert "[W2]" not in context
    assert "did not produce" in research.checked_studio_answer("Claim [W2].", rows)


def test_provider_wrong_shape_denied_before_enrichment():
    async def bad(_query):
        return {"unexpected": "dictionary"}

    async def no_fetch(_rows):
        pytest.fail("No verification on invalid provider result")

    with pytest.raises(TypeError, match="list"):
        asyncio.run(research.studio_research_sources("robotics recent updates", bad, enricher=no_fetch))


def test_named_person_relevance_gate_and_fallback():
    queries = []

    async def search(query):
        queries.append(query)
        if len(queries) == 1:
            return [record(title="Generic jobs", snippet="Employment verification service")]
        return [record(title="Muhammad Toqeer Ali research profile",
                       snippet="Muhammad Toqeer Ali published research at universities")]

    async def enrich(rows):
        assert all("Muhammad Toqeer Ali" in x["title"] for x in rows)
        return verified(rows)

    rows = asyncio.run(research.studio_research_sources(
        "Is Muhammad Toqeer Ali currently at KIOS?", search, enricher=enrich))
    assert len(queries) == 2
    assert "muhammad toqeer ali" in queries[0].lower()
    assert rows[0]["page_verified"] is True
    assert len(rows) == 1


def test_search_unsafe_url_excluded_by_shared_gateway():
    async def search(_query):
        return [record(url="http://127.0.0.1/private")]

    async def enrich(rows):
        assert rows == []
        return []

    rows = asyncio.run(research.studio_research_sources("robotics sources", search, enricher=enrich))
    assert rows == []


def test_prompt_and_evidence_budgets():
    verified_rows = []
    for i in range(6):
        verified_rows.append({**record(url=f"https://example.org/p{i}"),
                              "ref": f"W{i+1}", "page_verified": True,
                              "page_excerpt": "x" * 8000})
    assert len(research.studio_evidence_context(verified_rows)) <= research.MAX_EVIDENCE_CHARS
    assert "retrieved" in research.studio_source_scope(verified_rows).lower()
    with pytest.raises(ValueError):
        asyncio.run(research.studio_research_sources("x" * 6001, AsyncMock()))


def test_question_does_not_trigger_other_tool_types():
    # The only callable passed in is the fixed search adapter; URLs remain B10-owned.
    async def search(_query):
        return [record()]

    async def enrich(rows):
        return rows

    rows = asyncio.run(research.studio_research_sources("recent robotics", search, enricher=enrich))
    assert rows[0]["page_verified"] is False
