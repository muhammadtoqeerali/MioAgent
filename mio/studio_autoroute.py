"""Bounded, deterministic Studio tool selection based on the user's request.

This is intent routing, NOT a claim that a tool is online or that a model can
create images without a configured local raster backend. Attachments grant no tools.
"""

from __future__ import annotations

import re

_IMAGE_VERBS = re.compile(
    r"\b(?:generate|create|draw|render|make|design|paint|illustrate|sketch)\b", re.IGNORECASE
)
_IMAGE_OBJECTS = re.compile(
    r"\b(?:image|picture|photo|photograph|illustration|artwork|poster|logo|"
    r"wallpaper|portrait|infographic|diagram|visual|graphic|painting)\b", re.IGNORECASE
)
_DIRECT_IMAGE = re.compile(
    r"\b(?:text[- ]to[- ]image|generate an? (?:pic|img)|show me (?:an? )?"
    r"(?:picture|photo|image) of)\b", re.IGNORECASE
)
_WEB_INTENT = re.compile(
    r"\b(?:search (?:the )?(?:web|internet|online)|browse (?:the )?(?:web|internet)|"
    r"look up|find (?:online|on the web)|google|web search|online sources|"
    r"latest|breaking news|current news|today'?s? news|"
    r"right now|as of (?:today|now)|this (?:week|month|year)|"
    r"up[- ]to[- ]date|recent developments|recent news|"
    r"official website|check online|search for|verify online)\b", re.IGNORECASE
)
_WEB_FRESHNESS = re.compile(
    r"\b(?:current|today|tonight|tomorrow|yesterday|recent|now|2026|"
    r"news|weather|stock price|exchange rate|release date|"
    r"available|latest version|newest)\b", re.IGNORECASE
)
_NON_IMAGE_DELIVERABLE = re.compile(
    r"\b(?:report|summary|analysis|article|essay|comparison|website|web app|code|tutorial)\b", re.IGNORECASE
)
_DIRECT_DRAW = re.compile(
    r"^\s*(?:draw|paint|sketch|illustrate|render)\s+(?!conclusions?\b)", re.IGNORECASE
)
_EXPLANATION = re.compile(
    r"^\s*(?:explain|what (?:is|does|are)|how (?:does|do|can)|why|"
    r"can you tell me|describe)\b", re.IGNORECASE
)


def route_intent(prompt: str, kinds: list[str] | tuple[str, ...] = (),
                 requested: str = "auto") -> str:
    """Select image, research, analyze, or chat; explicit legacy modes still work.

    A model is never granted execution privileges by its own output. Obvious
    operations are routed without another GPU-heavy model call.
    """
    if requested not in ("auto", "chat", "research", "analyze", "image"):
        raise ValueError("Unknown Studio operation")
    if requested != "auto":
        return requested
    if not isinstance(prompt, str) or not prompt.strip():
        return "chat"
    text = prompt.strip()
    verb = _IMAGE_VERBS.search(text)
    obj = _IMAGE_OBJECTS.search(text)
    candidate = bool(_DIRECT_IMAGE.search(text) or _DIRECT_DRAW.search(text))
    if verb and obj and verb.start() < obj.start() and obj.start() - verb.end() < 90:
        # "Create a summary of image models" is a text task, not a raster job.
        candidate = candidate or not _NON_IMAGE_DELIVERABLE.search(text[:obj.start()])
    if candidate and not (_EXPLANATION.search(text) and not text.lower().startswith("show me")):
        return "image"
    if _WEB_INTENT.search(text):
        return "research"
    if _WEB_FRESHNESS.search(text):
        return "research"
    if kinds:
        return "analyze"
    return "chat"
