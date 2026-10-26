"""SCORPIO9D2: source-only policy and explicit review preservation."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from mio import work_engineering
from mio.scorpio9d1_textutils import PREFIX
from mio.work_core import create_project, create_run

GOOD = """import re

def normalize_whitespace(text):
    return " ".join(text.split())

def count_words(text):
    return len(text.split())

def is_palindrome(text):
    clean = "".join(ch.casefold() for ch in text if ch.isalnum())
    return clean == clean[::-1]

def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
"""


def test_plain_source_requested_by_textutils_profile(tmp_path, monkeypatch):
    root = tmp_path / "private" / "work"
    root.parent.mkdir(mode=0o700)
    project = create_project(root, "D2 source policy", "Synthetic prompt scope")
    run = create_run(root, project["id"], PREFIX + "Build offline text helpers", engineering=True)
    captured = []

    class FakeRouter:
        def __init__(self, _settings, role):
            assert role == "coding"

        async def complete(self, messages, max_tokens):
            captured.append(messages)
            return SimpleNamespace(text=GOOD, model="synthetic-local")

    monkeypatch.setattr(work_engineering, "FleetRouter", FakeRouter)
    result = asyncio.run(work_engineering.execute_engineering(root, run["id"], None))
    assert len(captured) == 1
    system = captured[0][0]["content"]
    assert "No JSON" in system
    assert "ONLY concise valid Python source" in system
    assert "additional files" in system
    assert result["state"] == "answered", result
    manifest, artifact = work_engineering.read_artifact(root, run["id"])
    assert set(artifact) == {"textutils.py"}
    assert manifest["verification"]["passed"] is True
    assert manifest["verification"]["tests_run"] == 13


def test_other_engineering_profile_remains_json(monkeypatch, tmp_path):
    root = tmp_path / "private" / "work"
    root.parent.mkdir(mode=0o700)
    project = create_project(root, "Existing coding policy", "Synthetic prompt scope")
    run = create_run(root, project["id"], "Create a small offline Python module", engineering=True)
    captured = []

    class FakeRouter:
        def __init__(self, _settings, role):
            assert role == "coding"

        async def complete(self, messages, max_tokens):
            captured.append(messages)
            return SimpleNamespace(text=json.dumps({"files": [{"path": "demo.py", "content": "def answer():\n    return 42\n"}]}), model="synthetic-local")

    monkeypatch.setattr(work_engineering, "FleetRouter", FakeRouter)
    result = asyncio.run(work_engineering.execute_engineering(root, run["id"], None))
    assert "JSON object" in captured[0][0]["content"]
    assert result["state"] == "needs_review"


def test_frontend_approval_policy_is_binary():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "apps/dashboard/app/_mio/scorpio-approval-panel.tsx").read_text()
    assert 'task_type: "engineering", approved: true' in source
    assert 'prompt: proposedPrompt' in source
    assert 'every(name => run.prompt.includes(name))' in source
    assert 'Reject — do nothing' in source
    assert 'event.phase === "validation.reject"' in source
    assert 'textarea' not in source
    assert 'task_type: "bounded"' not in source
    assert 'The original was not resumed' in source
    assert 'if (active) return' in source
    assert 'onClick={() => void approve()}' in source
    assert 'onClick={() => setRejected(true)}' in source
    assert 'const proposedPrompt = run.prompt.startsWith(ENGINEERING_PREFIX)' in source
    assert "platform's independent 13 tests" in source


def test_new_work_composer_requires_only_goal_and_approval():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "apps/dashboard/app/work-mode/page.tsx").read_text()
    assert 'What would you like Scorpio to do?' in source
    assert 'Approve & start' in source
    assert 'Reject — do nothing' in source
    assert 'task_type:proposedType,approved:true' in source
    assert 'const textutilsGoal = proposedType === "engineering"' in source
    assert 'SCORPIO9D1 TEXTUTILS: ${acceptedGoal}' in source
    assert 'Assignment title<input' not in source
    assert 'How will you verify success?' not in source
