"""SCORPIO9D1R2: data-only response-format recovery for pinned textutils jobs.

Never execute or trust model text. The only fallback translates one standalone
Python module into the *same* validated JSON artifact schema already accepted
by Work engineering. Final source verification remains entirely in Bubblewrap.
"""

from __future__ import annotations

import ast
import json
import re

MAX_REPLY_BYTES = 110_000
MAX_SOURCE_BYTES = 16_000
REQUIRED_FUNCTIONS = frozenset({
    "normalize_whitespace", "count_words", "is_palindrome", "slugify",
})
FENCE = re.compile(
    r"(?m)^```(?P<language>python|py|json)?[ \t]*\r?\n"
    r"(?P<body>.*?)\r?\n```[ \t]*(?=\r?\n|\Z)",
    re.DOTALL | re.IGNORECASE,
)


def _source_candidate(text: str) -> bool:
    if not text or len(text.encode("utf-8")) > MAX_SOURCE_BYTES:
        return False
    try:
        tree = ast.parse(text, filename="textutils.py")
    except (SyntaxError, ValueError, RecursionError):
        return False
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in REQUIRED_FUNCTIONS
        for node in tree.body
    )


def response_shape(raw: str) -> str:
    """Record a category only, never prompts, code, or raw model output."""
    if not isinstance(raw, str):
        return "non_text"
    if len(raw.encode("utf-8")) > MAX_REPLY_BYTES:
        return "oversized"
    value = raw.strip()
    if not value:
        return "empty"
    if value.startswith("{"):
        return "json_candidate"
    blocks = FENCE.findall(value)
    if len(blocks) == 1 and value.count("```") == 2:
        language, body = blocks[0]
        if language.lower() == "json" or body.lstrip().startswith("{"):
            return "fenced_json_candidate"
        if _source_candidate(body):
            return "fenced_python"
    if _source_candidate(value):
        return "plain_python"
    return "other"


def normalize_reply(raw: str, *, textutils: bool) -> str:
    """Normalize an unambiguous model reply to a JSON envelope, never a grant.

    Plain/fenced Python recovery applies only to explicitly owner-approved
    SCORPIO9D1 textutils tasks. A malformed JSON object is never reinterpreted
    as Python. Model-provided paths and test files are never substituted.
    """
    if not textutils or not isinstance(raw, str):
        return raw
    if len(raw.encode("utf-8")) > MAX_REPLY_BYTES:
        return raw
    value = raw.strip()
    if not value or value.startswith("{"):
        return raw
    blocks = FENCE.findall(value)
    if len(blocks) == 1 and value.count("```") == 2:
        language, body = blocks[0]
        if language.lower() == "json" or body.lstrip().startswith("{"):
            # Parsing is performed later by the unchanged strict Work JSON parser.
            return body.strip()
        if language.lower() not in ("python", "py", ""):
            return raw
        candidate = body.strip()
    elif "```" not in value:
        candidate = value
    else:
        return raw
    if not _source_candidate(candidate):
        return raw
    return json.dumps({"files": [{"path": "textutils.py", "content": candidate}]},
                      ensure_ascii=False)
