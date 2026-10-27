"""SCORPIO9D3B10: shared authenticated public-web research tool surface.

Search uses the existing provider/quality gate; open uses the existing pinned-
DNS, certificate-verified bounded HTTPS reader.  No model text grants tools.
This surface is read-only and does not issue Work browser grants or modify files.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from mio.studio_tools import web_search
from mio.web_evidence import EvidenceError, enrich_sources, fetch_public_page, public_target

MAX_SOURCES = 6
MAX_VERIFIED = 3
MAX_EXCERPT = 4000
REF = re.compile(r"\[W([1-6])\]")
ANY_REF = re.compile(r"\[W\d+\]")


class SearchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=350)


class OpenRequest(BaseModel):
    url: str = Field(min_length=12, max_length=1500)


def capabilities() -> dict:
    """Report implemented capabilities only; not provider availability."""
    return {
        "version": "scorpio9d3b10",
        "tools": [
            {"id": "web.search", "kind": "read_only", "provider": "fixed_public_search", "max_results": MAX_SOURCES},
            {"id": "web.open", "kind": "read_only", "max_bytes": 420000, "max_excerpt_chars": MAX_EXCERPT},
            {"id": "web.cite", "kind": "local_validation", "requires_verified_excerpt": True},
        ],
        "permissions": {"public_https_only": True, "no_redirects": True,
                        "private_network": False, "javascript": False,
                        "logins": False, "shell": False, "downloads": False,
                        "work_browser_grants": False},
        "availability": "providers_checked_per_request",
    }


def clean_record(record: dict, number: int) -> dict | None:
    """Treat upstream provider dictionaries as untrusted, including claimed verification."""
    if not isinstance(record, dict):
        return None
    title, url, snippet = (record.get(key) for key in ("title", "url", "snippet"))
    if not all(isinstance(x, str) for x in (title, url, snippet)):
        return None
    try:
        public_target(url)
    except (EvidenceError, TypeError, ValueError):
        return None
    if not title.strip():
        return None
    return {"ref": f"W{number}", "title": title[:160], "url": url,
            "snippet": snippet[:450], "page_verified": False,
            "page_excerpt": "", "scope": "search_snippet_only"}


def verified_record(record: dict) -> dict:
    """Convert a record only after the trusted retriever, never a search provider."""
    safe = clean_record(record, int(record["ref"][1:]))
    if safe is None:
        raise EvidenceError("Unusable public search result")
    if record.get("page_verified") is True and isinstance(record.get("page_excerpt"), str):
        excerpt = record["page_excerpt"].strip()[:MAX_EXCERPT]
        if excerpt:
            safe.update({"page_verified": True, "page_excerpt": excerpt,
                         "scope": "retrieved_public_page_excerpt"})
    return safe


async def search_open(query: str, *, search_fn=None, enrich_fn=None) -> dict:
    """Fixed public search, then up to six tries for three page excerpts."""
    if not isinstance(query, str) or not 3 <= len(query.strip()) <= 350:
        raise ValueError("Search query must contain 3-350 characters")
    search_fn = web_search if search_fn is None else search_fn
    enrich_fn = enrich_sources if enrich_fn is None else enrich_fn
    found = await search_fn(query.strip())
    if not isinstance(found, list):
        raise TypeError("Search provider returned unexpected evidence")
    filtered: list[dict] = []
    seen: set[str] = set()
    for record in found[:MAX_SOURCES]:
        safe = clean_record(record, len(filtered) + 1)
        if safe and safe["url"] not in seen:
            seen.add(safe["url"])
            filtered.append(safe)
    # Existing enricher resets untrusted provider verification fields and
    # calls the pinned-IP fetcher.  Do not trust a provider's page excerpt.
    enriched = await enrich_fn(filtered)
    if not isinstance(enriched, list) or len(enriched) != len(filtered):
        raise ValueError("Research evidence shape mismatch")
    sources = []
    for index, item in enumerate(enriched):
        if not isinstance(item, dict) or item.get("url") != filtered[index]["url"]:
            raise ValueError("Evidence provenance changed during retrieval")
        item = {**filtered[index], **item, "ref": filtered[index]["ref"]}
        sources.append(verified_record(item))
    count = sum(row["page_verified"] for row in sources)
    if count > MAX_VERIFIED:
        raise ValueError("Exceeded public page verification budget")
    return {"query": query.strip(), "sources": sources, "verified_count": count,
            "status": "verified_excerpts" if count else "snippets_only",
            "checked_at_utc": datetime.now(UTC).isoformat(),
            "limits": {"max_search_hits": MAX_SOURCES, "max_verified_pages": MAX_VERIFIED}}


async def open_public(url: str, *, fetcher=None) -> dict:
    """Read exactly one owner-provided public HTTPS URL without redirects."""
    public_target(url)
    fetcher = fetch_public_page if fetcher is None else fetcher
    page = await asyncio.to_thread(fetcher, url)
    if not isinstance(page, dict) or page.get("page_verified") is not True:
        raise EvidenceError("Public page was not verified")
    excerpt = page.get("page_excerpt")
    if not isinstance(excerpt, str) or not excerpt.strip():
        raise EvidenceError("Public page contained no readable evidence")
    return {"url": url, "page_verified": True, "page_excerpt": excerpt[:MAX_EXCERPT],
            "scope": "retrieved_public_page_excerpt", "checked_at_utc": datetime.now(UTC).isoformat()}


def check_citations(answer: str, sources: list[dict]) -> bool:
    """Validate source ID binding, not factual truth of an answer."""
    if not isinstance(answer, str) or not isinstance(sources, list):
        return False
    seen = {f"W{x}" for x in REF.findall(answer)}
    tokens = ANY_REF.findall(answer)
    available = {row.get("ref") for row in sources
                 if isinstance(row, dict) and row.get("page_verified") is True
                 and isinstance(row.get("page_excerpt"), str) and row["page_excerpt"].strip()}
    return bool(seen and seen <= available and all(token == f"[{token[1:-1]}]" and token[1:-1] in seen for token in tokens))


def register_public_research_routes(app: FastAPI, require_token: Callable) -> None:
    """Auth is inherited from native API; no public unauthenticated tool route."""
    auth = [Depends(require_token)]

    @app.get("/api/research/tools", dependencies=auth)
    def tool_catalog():
        return capabilities()

    @app.post("/api/research/search", dependencies=auth)
    async def search(payload: SearchRequest):
        try:
            return await search_open(payload.query)
        except (EvidenceError, ValueError, TypeError, OSError, RuntimeError) as exc:
            raise HTTPException(503, detail="Public search or verification unavailable") from exc

    @app.post("/api/research/open", dependencies=auth)
    async def open_page(payload: OpenRequest):
        try:
            return await open_public(payload.url)
        except (EvidenceError, ValueError, OSError, RuntimeError) as exc:
            raise HTTPException(422, detail="Public HTTPS page could not be verified") from exc
