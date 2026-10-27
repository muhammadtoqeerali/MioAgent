"""SCORPIO9D3B9R1: relevance gate for named-person public affiliation queries.

Pure deterministic text matching, with no I/O or permission side effects. When a
question has an extractable subject name, never turn a generic employment or
verification website into evidence about that named person.
"""

from __future__ import annotations

import re

_PERSON_QUESTION = re.compile(
    r"\b(?:does|did|is|was|whether|if)\s+"
    r"(?P<name>[a-z][a-z'-]*(?:\s+[a-z][a-z'-]*){1,6}?)\s+"
    r"(?:(?:currently|still|now)\s+)?"
    r"(?:works?|working|employed|affiliated|at|with|a\s+(?:researcher|staff\s+member))\b",
    re.IGNORECASE,
)
_WORDS = re.compile(r"[a-z0-9]+")
_TRIVIAL = frozenset({"he", "she", "they", "this", "that", "someone", "anyone"})


def person_name(prompt: str) -> str | None:
    """Read a likely 2–5-part person name, not arbitrary model-selected entities."""
    if not isinstance(prompt, str):
        return None
    match = _PERSON_QUESTION.search(prompt[:600])
    if match is None:
        return None
    name = match.group("name")
    parts = _WORDS.findall(name.lower())
    # Users sometimes say 'name person' after the actual person's name.
    while parts and parts[-1] in {"person", "name"}:
        parts.pop()
    if not 2 <= len(parts) <= 5 or parts[0] in _TRIVIAL:
        return None
    return " ".join(parts)


def _name_in_record(name: str, record: dict) -> bool:
    """Match full ordered names, or common 'Surname, Given Middle' listings."""
    if not isinstance(record, dict):
        return False
    title = record.get("title")
    snippet = record.get("snippet")
    if not isinstance(title, str) or not isinstance(snippet, str):
        return False
    terms = _WORDS.findall((title + " " + snippet).lower())
    expected = name.split()
    variants = (expected, [expected[-1], *expected[:-1]])
    return any(
        terms[i:i + len(variant)] == variant
        for variant in variants
        for i in range(len(terms) - len(variant) + 1)
    )


def relevant_person_results(prompt: str, records: list[dict]) -> list[dict]:
    """Exclude generic portals or near-name collisions from person employment evidence."""
    name = person_name(prompt)
    if name is None:
        return records
    return [item for item in records if _name_in_record(name, item)]


def focused_query(prompt: str) -> str | None:
    """Prefer subject name to action verbs such as 'verify' or 'work'."""
    name = person_name(prompt)
    if name is None:
        return None
    site = " KIOS" if re.search(r"\bkios\b", prompt, re.IGNORECASE) else ""
    return f'"{name}"{site} researcher'


def fallback_query(prompt: str) -> str | None:
    """At most one less-restrictive person-only retry in the caller."""
    name = person_name(prompt)
    if name is None:
        return None
    return f'"{name}"'
