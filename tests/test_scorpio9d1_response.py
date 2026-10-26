"""SCORPIO9D1R2: synthetic response-format recovery and worker engineering tests."""

from __future__ import annotations

import asyncio
import json
import shutil
from types import SimpleNamespace

import pytest

from mio import scorpio9d1_response as response
from mio import work_engineering
from mio.scorpio9d1_textutils import PREFIX
from mio.work_core import create_project, create_run

GOOD = '''import re

def normalize_whitespace(text: str) -> str:
    return " ".join(text.split())

def count_words(text: str) -> int:
    cleaned = normalize_whitespace(text)
    return len(cleaned.split(" ")) if cleaned else 0

def is_palindrome(text: str) -> bool:
    chars = "".join(c.casefold() for c in text if c.isalnum())
    return chars == chars[::-1]

def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
'''
BAD = 'def normalize_whitespace(text):\n    return "incorrect"\n'
PROMPT = PREFIX + "Build the four offline Python text utility functions."


@pytest.mark.parametrize("raw", [
    GOOD,
    "```python\n" + GOOD.rstrip() + "\n```",
    "The source module follows:\n\n```py\n" + GOOD.rstrip() + "\n```\n",
])
def test_accepts_single_pure_python_artifact(raw):
    normalized = response.normalize_reply(raw, textutils=True)
    result = work_engineering.parse_draft(normalized)
    assert set(result) == {"textutils.py"}
    assert "def slugify" in result["textutils.py"]


def test_single_fenced_json_uses_unchanged_strict_schema():
    item = json.dumps({"files": [{"path": "textutils.py", "content": GOOD}]})
    actual = response.normalize_reply("```json\n" + item + "\n```", textutils=True)
    assert work_engineering.parse_draft(actual) == {"textutils.py": GOOD}


@pytest.mark.parametrize("payload", [
    "Only a narrative; no source code was supplied",
    "```python\n" + GOOD + "```\n```python\n" + GOOD + "```",
    "```python\nprint('first')\n```\n```python\nprint('second')\n```",
    json.dumps({"files": [{"path": "../../outside.py", "content": GOOD}]}),
    "x" * (response.MAX_REPLY_BYTES + 1),
])
def test_never_translates_untrusted_ambiguous_model_output(payload):
    if payload.startswith("{"):
        unchanged = response.normalize_reply(payload, textutils=True)
        assert unchanged == payload
        with pytest.raises(ValueError):
            work_engineering.parse_draft(unchanged)
    else:
        assert response.normalize_reply(payload, textutils=True) == payload


def test_other_work_profiles_unchanged():
    assert response.normalize_reply(GOOD, textutils=False) == GOOD
    assert response.response_shape(GOOD) == "plain_python"
    assert response.response_shape("```python\n" + GOOD + "```") in {
        "fenced_python", "other",
    }
    assert response.response_shape("private prompt hidden") == "other"


def test_missing_one_function_does_not_mint_tests_or_permissions():
    wrapped = response.normalize_reply(BAD, textutils=True)
    parsed = work_engineering.parse_draft(wrapped)
    assert set(parsed) == {"textutils.py"}
    assert "test_textutils_acceptance.py" not in parsed


def test_pure_python_response_real_bwrap_repair_cycle(tmp_path, monkeypatch):
    if shutil.which("bwrap") is None:
        pytest.fail("Mandatory real Bubblewrap absent")
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    root = private / "work"
    project = create_project(root, "R2 fixture", "Synthetic test only")
    run = create_run(root, project["id"], PROMPT, engineering=True)
    seen = []

    class FakeRouter:
        def __init__(self, _settings, role):
            assert role == "coding"

        async def complete(self, messages, max_tokens):
            seen.append(messages)
            payload = ("```python\n" + GOOD.rstrip() + "\n```"
                       if len(seen) == 2 else BAD)
            return SimpleNamespace(text=payload, model="synthetic-no-network")

    monkeypatch.setattr(work_engineering, "FleetRouter", FakeRouter)
    result = asyncio.run(work_engineering.execute_engineering(root, run["id"], None))
    assert len(seen) == 2
    assert result["state"] == "answered", result
    manifest, files = work_engineering.read_artifact(root, run["id"])
    assert set(files) == {"textutils.py"}
    assert manifest["verification"]["passed"] is True
    assert manifest["verification"]["tests_run"] == 13
    assert sum(ev["phase"] == "model.format_recovered" for ev in result["events"]) == 2
    assert sum(ev["phase"] == "sandbox.verify" for ev in result["events"]) == 2
