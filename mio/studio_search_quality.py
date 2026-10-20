"""Relevance-aware, bounded search augmentation for MioAgent Studio.

Search providers can return navigational homepages for instructions such as
"search the web for X". Never present those homepages as research evidence.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx

from mio.studio_files import StudioError

_UNHELPFUL = frozenset({
    "a", "about", "and", "are", "at", "by", "cited", "current", "development",
    "developments", "find", "for", "from", "give", "how", "in", "include", "into",
    "is", "latest", "me", "new", "news", "of", "on", "online", "recent",
    "results", "search", "source", "sources", "study", "studies", "the", "three", "official",
    "to", "today", "update", "updates", "web", "what", "with", "you",
})
_PORTALS = frozenset({
    "google.com", "bing.com", "yahoo.com", "duckduckgo.com", "search.brave.com",
    "search.google.com", "search.yahoo.com", "search.yahoo.co.jp",
})
_PREFIX = re.compile(
    r"^\s*(?:(?:please|can you|could you|would you)\s+)*"
    r"(?:search\s+(?:the\s+)?(?:web|internet|online)\s+for|"
    r"look\s+up|find\s+(?:online\s+)?(?:information\s+(?:on|about)\s+)?|"
    r"research|browse\s+(?:the\s+)?(?:web|internet)\s+for|"
    r"check\s+(?:online\s+)?(?:for|about))\s+",
    re.IGNORECASE,
)
_OUTPUT = re.compile(
    r"\s+(?:(?:and|then)\s+)?(?:give|provide|list|show|include|"
    r"summarize|cite)\s+(?:me\s+)?(?:\d+|one|two|three|four|five|six)?"
    r"\s*(?:cited\s+)?(?:findings|developments|sources|results|links|papers|articles|"
    r"citations|examples|points|updates|a\s+summary|an\s+answer)\b.*$",
    re.IGNORECASE,
)
_WORD = re.compile(r"[a-z0-9]+")


def search_query(prompt: str) -> str:
    """Remove search instructions/output formatting while retaining subject terms."""
    if not isinstance(prompt, str) or not 3 <= len(prompt.strip()) <= 350:
        raise StudioError("Search requires a question of 3–350 characters")
    candidate = _PREFIX.sub("", prompt.strip(), count=1)
    candidate = _OUTPUT.sub("", candidate, count=1).strip(" \t\n\r.,:;?!")
    if len(candidate) < 3:
        candidate = prompt.strip()
    return candidate[:350]


def _stem(word: str) -> str:
    if word in {"robotics", "robotic", "robots"}:
        return "robot"
    if word.endswith("ies") and len(word) > 5:
        return word[:-3] + "y"
    if word.endswith("s") and not word.endswith("ss") and len(word) > 4:
        return word[:-1]
    return word


def focus_terms(query: str) -> tuple[str, ...]:
    words = (_stem(w) for w in _WORD.findall(query.lower()))
    return tuple(dict.fromkeys(w for w in words if w not in _UNHELPFUL and len(w) > 2))[:14]


def _portal(url: str, focus: tuple[str, ...]) -> bool:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if any(host == p or host.endswith("." + p) for p in _PORTALS):
        return not any(x in focus for x in ("google", "bing", "yahoo", "duckduckgo", "brave"))
    return False


def relevant_results(results: list[dict], query: str) -> list[dict]:
    """Select actual topical sources; no provider homepage masquerading as a citation."""
    focus = focus_terms(query)
    # If there are no distinctive topic terms, use provider data only after excluding portals.
    minimum = 2 if len(focus) >= 3 else 1
    ranked: list[tuple[int, int, dict]] = []
    seen: set[str] = set()
    for pos, row in enumerate(results):
        if not isinstance(row, dict):
            continue
        url = row.get("url")
        title = row.get("title")
        snippet = row.get("snippet")
        if not all(isinstance(x, str) for x in (url, title, snippet)):
            continue
        if url in seen or _portal(url, focus):
            continue
        if not url.startswith("https://"):
            continue
        text = " ".join((title, snippet, urlparse(url).hostname or ""))
        words = {_stem(x) for x in _WORD.findall(text.lower())}
        match = sum(term in words for term in focus)
        if focus and match < minimum:
            continue
        if not title.strip() or not snippet.strip():
            continue
        seen.add(url)
        ranked.append((match, pos, {"title": title[:160], "snippet": snippet[:450],
                                     "url": url}))
    ranked.sort(key=lambda p: (-p[0], p[1]))
    return [{"ref": f"W{i + 1}", **entry} for i, (_, _, entry) in enumerate(ranked[:6])]


async def quality_search(
    prompt: str,
    client: httpx.AsyncClient | None,
    provider_search: Callable[[str, httpx.AsyncClient], Awaitable[list[dict]]],
    duck_search: Callable[[str, httpx.AsyncClient], Awaitable[list[dict]]],
) -> list[dict]:
    """Try focused search and a second provider; fail visibly on irrelevant results."""
    clean = search_query(prompt)
    owned = client is None
    if client is None:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(18, connect=6), follow_redirects=False,
            trust_env=False, headers={"User-Agent": "MioAgent/0.4J research"},
        )
    try:
        all_results: list[dict] = []
        provider_unavailable = False
        try:
            all_results.extend(await provider_search(clean, client))
        except StudioError as exc:
            provider_unavailable = "unavailable" in str(exc).lower()
        except (httpx.HTTPError, ValueError, ElementTree.ParseError):
            provider_unavailable = True
        selected = relevant_results(all_results, clean)
        # A good single result satisfies a query that did not request a count.
        # For a stated quantity (e.g. three sources), try the second provider.
        if not selected or (len(selected) < 3 and re.search(r"\b(?:3|three)\b", prompt, re.IGNORECASE)):
            try:
                all_results.extend(await duck_search(clean, client))
            except (StudioError, httpx.HTTPError, ValueError):
                pass
            selected = relevant_results(all_results, clean)
        # Narrow awkward natural-language queries further without fabricating results.
        shorter = " ".join(focus_terms(clean))
        if not selected and shorter and shorter.lower() != clean.lower():
            try:
                all_results.extend(await provider_search(shorter, client))
                all_results.extend(await duck_search(shorter, client))
            except (StudioError, httpx.HTTPError, ValueError, ElementTree.ParseError):
                pass
            selected = relevant_results(all_results, clean)
        if not selected:
            if provider_unavailable and not all_results:
                raise StudioError("Public search providers unavailable; no evidence was collected")
            raise StudioError(
                "Search providers returned no topic-relevant sources. "
                "The assistant will not cite unrelated search-engine homepages."
            )
        return selected
    finally:
        if owned:
            await client.aclose()
