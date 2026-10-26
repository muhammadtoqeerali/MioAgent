"""SCORPIO9D1 acceptance contracts; only synthetic temporary Work databases."""

from __future__ import annotations

import asyncio
import json
import shutil
from types import SimpleNamespace

import pytest

from mio import scorpio9d1_textutils as scope
from mio import work_engineering
from mio.work_core import WorkStop, create_project, create_run, run_info

GOOD = '''import re

def normalize_whitespace(text: str) -> str:
    return " ".join(text.split())

def count_words(text: str) -> int:
    cleaned = normalize_whitespace(text)
    return len(cleaned.split(" ")) if cleaned else 0

def is_palindrome(text: str) -> bool:
    chars = "".join(ch.casefold() for ch in text if ch.isalnum())
    return chars == chars[::-1]

def slugify(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")
'''
BAD = "def count_words(text): return 111\n"
PROMPT = scope.PREFIX + "Build a small reusable offline library with four functions."


def test_requires_explicit_opt_in_prefix():
    assert scope.is_contract(PROMPT)
    assert not scope.is_contract("Build a text utility library")
    assert not scope.is_contract(scope.PREFIX)
    assert not scope.is_contract(scope.PREFIX + "short")


@pytest.mark.parametrize("files", [
    {"README.md": "readme"},
    {"textutils.py": GOOD, "test_custom.py": "assert False"},
    {"textutils.py": GOOD, "../../host.py": "print(1)"},
    {"textutils.py": GOOD, "re.py": "raise Exception('override')"},
    {"textutils.py": " "},
    {"textutils.py": "a" * (scope.MAX_CODE_BYTES + 1)},
    {"textutils.py": GOOD, "README.md": "a" * (scope.MAX_README_BYTES + 1)},
])
def test_rejects_noncontract_names_and_limits(files):
    with pytest.raises(WorkStop):
        scope._review_names(files)


def test_model_output_never_supplies_acceptance_tests():
    assert scope.TEST_COUNT == 13
    assert "class TextUtilitiesAcceptance" in scope.TRUSTED_TEST
    assert "from textutils import" in scope.TRUSTED_TEST
    assert "MIO_VERIFIER_TESTS_RUN=" in __import__(
        "mio.sandbox_verify", fromlist=["HARNESS"]
    ).HARNESS
    assert "test_textutils_acceptance.py" not in {scope.MODULE, "README.md"}


def test_parser_rejects_model_created_test_source():
    payload = {"files": [{"path": "textutils.py", "content": GOOD},
                         {"path": "test_textutils_acceptance.py", "content": "assert 1 == 1"}]}
    with pytest.raises(WorkStop):
        work_engineering.parse_draft(json.dumps(payload))


def test_missing_bwrap_fails_closed(tmp_path, monkeypatch):
    def unavailable(_staging, _code):
        raise OSError("bwrap unavailable")

    monkeypatch.setattr(scope, "sandbox_argv", unavailable)
    outcome = scope.verify({"textutils.py": GOOD}, tmp_path)
    assert outcome["status"] == "sandbox_unavailable"
    assert outcome["passed"] is False


def test_mocked_failed_trusted_tests_never_pass(tmp_path, monkeypatch):
    responses = iter([(0, "MIO_SANDBOX_PREFLIGHT_OK", False, False),
                      (0, "MIO_VERIFIER_TESTS_RUN=12", False, False)])
    monkeypatch.setattr(scope, "sandbox_argv", lambda _staging, _code: ["safe-program"])
    monkeypatch.setattr(scope, "_bounded_run", lambda *_args, **_kw: next(responses))
    outcome = scope.verify({"textutils.py": GOOD}, tmp_path)
    assert outcome["passed"] is False
    assert outcome["tests_run"] == 12


def test_mocked_network_isolation_preflight_mandatory(tmp_path, monkeypatch):
    monkeypatch.setattr(scope, "sandbox_argv", lambda _staging, _code: ["safe-program"])
    monkeypatch.setattr(
        scope, "_bounded_run", lambda *_args, **_kw: (0, "not a valid preflight", False, False)
    )
    outcome = scope.verify({"textutils.py": GOOD}, tmp_path)
    assert outcome["passed"] is False
    assert outcome["status"] == "sandbox_unavailable"


def test_real_bwrap_contract_suite(tmp_path):
    if shutil.which("bwrap") is None:
        pytest.fail("SCORPIO9D1 requires working OS Bubblewrap before publication")
    good = scope.verify({"textutils.py": GOOD}, tmp_path)
    assert good["status"] == "passed", good
    assert good["tests_run"] == 13
    broken = scope.verify({"textutils.py": BAD}, tmp_path)
    assert broken["passed"] is False
    assert broken["status"] == "failed"


def test_repair_loop_and_artifact_e2e(tmp_path, monkeypatch):
    if shutil.which("bwrap") is None:
        pytest.fail("OS Bubblewrap required for engineering end-to-end acceptance")
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    root = private / "work"
    project = create_project(root, "Text utilities engineering", "Synthetic only")
    run = create_run(root, project["id"], PROMPT, engineering=True)
    turns = [BAD, GOOD]
    submitted = []

    class FakeRouter:
        def __init__(self, _settings, role):
            assert role == "coding"

        async def complete(self, messages, max_tokens):
            submitted.append(messages)
            index = len(submitted) - 1
            return SimpleNamespace(text=json.dumps({"files": [
                {"path": "textutils.py", "content": turns[index]}
            ]}), model="fixture-no-network")

    monkeypatch.setattr(work_engineering, "FleetRouter", FakeRouter)
    outcome = asyncio.run(work_engineering.execute_engineering(root, run["id"], None))
    assert len(submitted) == 2
    assert any("PINNED SCORPIO9D1" in m["content"] for m in submitted[0] if m["role"] == "user")
    assert outcome["state"] == "answered", outcome
    assert outcome["model"] == "fixture-no-network"
    meta, files = work_engineering.read_artifact(root, run["id"])
    assert files == {"textutils.py": GOOD.encode()}
    assert meta["verification"]["passed"] is True
    assert meta["verification"]["tests_run"] == 13
    assert any(e["phase"] == "sandbox.verify" for e in run_info(root, run["id"])["events"])


def test_unapproved_task_cannot_directly_run_engineer(tmp_path, monkeypatch):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    root = private / "work"
    project = create_project(root, "No grant", "Only synthetic fixture")
    run = create_run(root, project["id"], PROMPT, engineering=False)
    monkeypatch.setattr(
        work_engineering, "FleetRouter", lambda *_: pytest.fail("Model not authorized")
    )
    with pytest.raises(WorkStop, match="owner approval"):
        asyncio.run(work_engineering.execute_engineering(root, run["id"], None))
    assert run_info(root, run["id"])["state"] == "queued"


def test_no_d1_gates_other_coding_requests():
    assert "SCORPIO9D1" not in work_engineering.CALCULATOR_TEST
    assert not scope.is_contract("Build a scientific calculator with add/multiply")
    # Existing calculator path remains independent and unchanged.
    assert "Scientific calculator must provide calculator.py" in __import__(
        "inspect").getsource(work_engineering._verification)
