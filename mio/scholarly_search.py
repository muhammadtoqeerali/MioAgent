"""Bounded public Crossref bibliographic search for explicitly scholarly Work goals.

Only a fixed public API is contacted. Results are journal metadata, not proof
of peer review or verification of article full text. Never follow result URLs.
"""

from __future__ import annotations

import html
import re
from urllib.parse import quote

import httpx

from mio.studio_files import StudioError
from mio.studio_search_quality import relevant_results

CROSSREF_URL = "https://api.crossref.org/works"
DOI = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\Z")
MAX_RESPONSE = 850_000


def _plain(value: object, length: int) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]{0,400}>", " ", value))).strip()[:length]


def _year(item: dict) -> str:
    data = item.get("published", {})
    if not isinstance(data, dict):
        return ""
    parts = data.get("date-parts")
    if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
        year = parts[0][0]
        if isinstance(year, int) and 1900 <= year <= 2100:
            return str(year)
    return ""


def _records(payload: dict, topic: str) -> list[dict]:
    content = payload.get("message", {}) if isinstance(payload, dict) else {}
    items = content.get("items", []) if isinstance(content, dict) else []
    if not isinstance(items, list):
        raise StudioError("Scholarly provider returned an invalid item list")
    candidates = []
    for item in items[:20]:
        if not isinstance(item, dict) or item.get("type") != "journal-article":
            continue
        titles = item.get("title")
        doi = item.get("DOI", "")
        if not isinstance(titles, list) or not titles or not isinstance(doi, str) or not DOI.fullmatch(doi):
            continue
        title = _plain(titles[0], 160)
        if not title:
            continue
        venue = item.get("container-title")
        journal = _plain(venue[0] if isinstance(venue, list) and venue else "", 100)
        year = _year(item)
        abstract = _plain(item.get("abstract"), 280)
        snippet = f"Crossref journal-article metadata; venue: {journal or 'not supplied'}; publication year: {year or 'unknown'}."
        if abstract:
            snippet += f" Deposited abstract excerpt: {abstract}"
        else:
            snippet += " Abstract unavailable; methods and peer-review status not independently verified."
        url = "https://doi.org/" + quote(doi, safe="/._-;()")
        candidates.append({"title": title, "url": url, "snippet": snippet[:450]})
    return relevant_results(candidates, topic)


async def scholarly_search(topic: str, client: httpx.AsyncClient | None = None) -> list[dict]:
    """Retrieve relevant journal metadata; never fetch DOI/article links or other hosts."""
    if not isinstance(topic, str) or not 3 <= len(topic.strip()) <= 180:
        raise StudioError("Invalid scholarly topic length")
    owned = client is None
    if client is None:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(22, connect=6), trust_env=False,
            follow_redirects=False,
            headers={"User-Agent": "MioAgent/0.4K (bibliographic metadata research)"},
        )
    try:
        try:
            response = await client.get(CROSSREF_URL, params={
                "query.bibliographic": topic.strip(), "filter": "type:journal-article",
                "rows": "20", "select": "DOI,title,type,abstract,published,container-title",
            })
            if response.status_code != 200 or len(response.content) > MAX_RESPONSE:
                raise StudioError(f"Crossref unavailable or response exceeded limit (HTTP {response.status_code})")
            results = _records(response.json(), topic)
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise StudioError(f"Crossref metadata request unavailable ({type(exc).__name__})") from exc
        if not results:
            raise StudioError("Crossref supplied no topic-relevant journal metadata")
        return results
    finally:
        if owned:
            await client.aclose()
