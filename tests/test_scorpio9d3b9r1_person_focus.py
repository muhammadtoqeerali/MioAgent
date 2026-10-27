"""SCORPIO9D3B9R1: no generic verification site as proof about a person."""

import asyncio
from types import SimpleNamespace

import pytest

from mio import scorpio9d3b9_chat_research as research
from mio.scorpio9d3b9r1_person_focus import (
    fallback_query,
    focused_query,
    person_name,
    relevant_person_results,
)


@pytest.mark.parametrize(("question", "name"), [
    ("verify online anywhere if muhammad toqeer ali work currently in KIOS", "muhammad toqeer ali"),
    ("check till today does muhammad toqeer ali name person work as researcher at KIOS", "muhammad toqeer ali"),
    ("Is Muhammad Toqeer Ali currently a researcher at KIOS?", "muhammad toqeer ali"),
    ("Does Jane Smith work at the University?", "jane smith"),
    ("Is John O'Neil still employed in academia?", "john o neil"),
    ("Please research modern robotics", None),
    ("Is she still employed at the institute?", None),
])
def test_person_extraction(question, name):
    assert person_name(question) == name


def test_search_query_retains_exact_person_instead_of_verify_portal():
    prompt = "verify online anywhere if muhammad toqeer ali work currently in the KIOS research center cyprus or not?"
    assert focused_query(prompt) == '"muhammad toqeer ali" KIOS researcher'
    assert fallback_query(prompt) == '"muhammad toqeer ali"'
    assert research._query(prompt) == focused_query(prompt)


def test_name_gate_excludes_us_employment_verification_and_partial_name():
    prompt = "Does Muhammad Toqeer Ali work at KIOS?"
    rows = [
        {"title": "E-Verify Employment Eligibility", "url": "https://www.e-verify.gov/", "snippet": "Verify jobs online"},
        {"title": "Muhammad Ali scientist", "url": "https://example.org/a", "snippet": "Researchers"},
        {"title": "Muhammad Toqeer Ali | Researcher", "url": "https://example.org/m", "snippet": "University of Verona"},
        {"title": "Ali, Muhammad Toqeer", "url": "https://example.org/v", "snippet": "PhD profile"},
    ]
    assert [row["url"] for row in relevant_person_results(prompt, rows)] == [
        "https://example.org/m", "https://example.org/v",
    ]


def test_nonperson_research_keeps_existing_results():
    rows = [{"title": "Physics math reference", "snippet": "sqrt"}]
    assert relevant_person_results("What is the latest Python version?", rows) == rows
    assert focused_query("What is the latest Python version?") is None


class _LocalModel:
    def __init__(self):
        self.calls = []

    async def complete(self, messages, max_tokens):
        self.calls.append(messages)
        return SimpleNamespace(text="The evidence does not establish a current KIOS appointment [W1].",
                               model="local-test", provider="local")


def test_irrelevant_first_search_retries_and_only_named_person_cited(monkeypatch):
    calls = []

    async def lookup(query):
        calls.append(query)
        if len(calls) == 1:
            return [{"title": "E-Verify", "snippet": "Verify an employee", "url": "https://www.e-verify.gov/"}]
        return [{"title": "Muhammad Toqeer Ali academic profile", "snippet": "Research Associate at University of Verona", "url": "https://example.org/ali"}]

    async def enrich(rows):
        assert len(rows) == 1 and rows[0]["url"] == "https://example.org/ali"
        return [{**rows[0], "page_verified": True, "page_excerpt": "Muhammad Toqeer Ali is listed with University of Verona in 2026."}]

    monkeypatch.setattr(research, "web_search", lookup)
    monkeypatch.setattr(research, "enrich_sources", enrich)
    model = _LocalModel()
    result = asyncio.run(research.research_chat(model, "verify online if muhammad toqeer ali work currently in KIOS"))
    assert len(calls) == 2
    assert "e-verify" not in result.answer.lower()
    assert "example.org/ali" in result.answer
    assert result.verified_sources == 1
    assert len(model.calls) == 1


def test_two_irrelevant_searches_fail_closed_no_fetch_no_model(monkeypatch):
    calls = []

    async def lookup(query):
        calls.append(query)
        return [{"title": "E-Verify", "snippet": "Employees", "url": "https://www.e-verify.gov/"}]

    async def must_not_fetch(_rows):
        raise AssertionError("Irrelevant site was sent to HTTPS client")

    monkeypatch.setattr(research, "web_search", lookup)
    monkeypatch.setattr(research, "enrich_sources", must_not_fetch)
    model = _LocalModel()
    result = asyncio.run(research.research_chat(model, "Is Muhammad Toqeer Ali currently at KIOS?"))
    assert len(calls) == 2
    assert not result.sources
    assert "e-verify" not in result.answer.lower()
    assert result.evidence_status == "unavailable"
    assert model.calls == []


def test_name_matched_but_no_verified_page_not_treated_as_employment(monkeypatch):
    async def lookup(query):
        return [{"title": "Muhammad Toqeer Ali", "snippet": "Academic profile", "url": "https://example.org/ali"}]

    async def enrich(rows):
        return rows

    monkeypatch.setattr(research, "web_search", lookup)
    monkeypatch.setattr(research, "enrich_sources", enrich)
    model = _LocalModel()
    result = asyncio.run(research.research_chat(model, "Does Muhammad Toqeer Ali work at KIOS?"))
    assert result.verified_sources == 0
    assert result.evidence_status == "snippets_only"
    assert model.calls == []
