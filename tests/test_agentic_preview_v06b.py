"""AGENT6B isolated deterministic and filesystem boundary regressions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mio.agentic_plan_v06b import (
    MAX_GOAL,
    MAX_SOURCES,
    AgenticPreviewDenied,
    plan,
    validate_source,
)
from mio.agentic_preview_v06b import _read_exact_source, execute_owner_preview, inspect


@pytest.fixture
def fake_project(tmp_path):
    repo = tmp_path / "MioAgent"
    (repo / "mio").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "docs").mkdir()
    (repo / "mio" / "engine.py").write_text("def inspect():\n    return 42\n", encoding="utf-8")
    (repo / "tests" / "test_engine.py").write_text("def test_yes():\n    assert True\n", encoding="utf-8")
    (repo / "docs" / "roadmap.md").write_text("# Plan\n", encoding="utf-8")
    return repo


def test_plan_five_steps_and_approval_blocked():
    p = plan("Fix an error in the Work engine", ["mio/engine.py"])
    assert p.kind == "repair"
    assert [stage["id"] for stage in p.stages] == ["scope", "inspect", "analyze", "handoff", "future"]
    assert p.stages[-1]["status"] == "blocked"
    assert p.approved_capabilities == ("preview.inspect",)
    assert "workspace.write" in p.requested_capabilities


@pytest.mark.parametrize(("goal", "kind"), [
    ("Implement agent planning", "implement"),
    ("Review source rules", "audit"),
    ("Understand a program", "explore"),
])
def test_intent_routing(goal, kind):
    assert plan(goal, ["mio/engine.py"]).kind == kind


@pytest.mark.parametrize("value", ["", "hi", "a" * (MAX_GOAL + 1), 45, "hello\x00 world"])
def test_unbounded_goals_refused(value):
    with pytest.raises(AgenticPreviewDenied):
        plan(value, ["mio/engine.py"])


@pytest.mark.parametrize("value", [
    "../../etc/passwd", "mio/../secrets/a.py", ".mioagent-private/state/secret.py",
    "mio/.env", "mio/secret.key", "mio/folder\\pass.py", "/mio/a.py",
    "mio//x.py", "other/file.py", "mio/models/x.py", "mio/.hidden.py",
    "mio/node_modules/malicious.py", "mio/a.json", "mio/x.py/.", "mio/.",
])
def test_private_traversal_and_unwanted_types_denied(value):
    with pytest.raises(AgenticPreviewDenied):
        validate_source(value)


def test_duplicate_and_too_many_sources_refused():
    with pytest.raises(AgenticPreviewDenied):
        plan("Inspect engine source", ["mio/engine.py", "mio/engine.py"])
    with pytest.raises(AgenticPreviewDenied):
        plan("Inspect engine source", ["mio/engine.py"] * (MAX_SOURCES + 1))


def test_openat_read_and_ast_structure(fake_project):
    p = plan("Review source engine", ["mio/engine.py"])
    details = inspect(fake_project, p)
    assert len(details) == 1
    assert details[0]["static_syntax"] == "parsed"
    assert details[0]["definitions"] == [{"kind": "function", "name": "inspect", "line": 1}]
    assert details[0]["sha256"] == hashlib.sha256((fake_project / "mio/engine.py").read_bytes()).hexdigest()


def test_read_never_executes_untrusted_python(fake_project):
    marker = fake_project / "SHOULD_NOT_EXIST"
    (fake_project / "mio/engine.py").write_text(
        "__import__('pathlib').Path(" + repr(str(marker)) + ").write_text('BAD')\n")
    p = plan("Inspect without executing", ["mio/engine.py"])
    assert inspect(fake_project, p)[0]["static_syntax"] == "parsed"
    assert not marker.exists()


def test_source_symlink_escape_is_refused(fake_project):
    (fake_project / "mio/sneaky.py").symlink_to("/etc/passwd")
    with pytest.raises(AgenticPreviewDenied):
        _read_exact_source(fake_project, "mio/sneaky.py")


def test_ancestor_symlink_escape_is_refused(fake_project):
    (fake_project / "mio/linked").symlink_to("/etc")
    with pytest.raises(AgenticPreviewDenied):
        _read_exact_source(fake_project, "mio/linked/passwd.py")


def test_directory_target_denied(fake_project):
    (fake_project / "mio/dir.py").mkdir()
    with pytest.raises(AgenticPreviewDenied):
        _read_exact_source(fake_project, "mio/dir.py")


def test_oversized_source_denied(fake_project):
    (fake_project / "mio/engine.py").write_bytes(b"x" * 256_001)
    with pytest.raises(AgenticPreviewDenied):
        _read_exact_source(fake_project, "mio/engine.py")


def test_syntax_error_reported_without_execution(fake_project):
    (fake_project / "mio/engine.py").write_text("def missing(:\n")
    d = inspect(fake_project, plan("Inspect broken source", ["mio/engine.py"]))[0]
    assert d["static_syntax"] == "syntax_error" and d["syntax_error_line"] == 1


def test_receipt_is_new_hash_verified_and_no_source_content(fake_project):
    src = fake_project / "mio/engine.py"
    before = src.read_bytes()
    result = execute_owner_preview(fake_project, "Review existing Work source", ["mio/engine.py"])
    receipt = Path(result["receipt_path"])
    assert receipt.is_relative_to(fake_project / ".mioagent-private/agents/audit/agent6b")
    assert hashlib.sha256(receipt.read_bytes()).hexdigest() == result["receipt_sha256"]
    payload = json.loads(receipt.read_text())
    assert payload["status"] == "needs_owner_review"
    assert payload["code_changed"] is False
    assert payload["tests_executed"] is False
    assert payload["live_work_connected"] is False
    assert payload["persistent_grants_issued"] is False
    assert "return 42" not in receipt.read_text()
    assert src.read_bytes() == before


def test_second_review_creates_another_immutable_receipt(fake_project):
    first = execute_owner_preview(fake_project, "Review existing Work source", ["mio/engine.py"])
    original = Path(first["receipt_path"]).read_bytes()
    second = execute_owner_preview(fake_project, "Review existing Work source", ["mio/engine.py"])
    assert first["receipt_path"] != second["receipt_path"]
    assert Path(first["receipt_path"]).read_bytes() == original


def test_audit_symlink_rejected(fake_project):
    (fake_project / ".mioagent-private").symlink_to("/tmp")
    with pytest.raises(AgenticPreviewDenied):
        execute_owner_preview(fake_project, "Review existing Work source", ["mio/engine.py"])


def test_no_extra_files_outside_project(fake_project, tmp_path):
    # tests/conftest.py creates isolated-fleet before the test starts. Capture the
    # actual pre-existing siblings; only new writes outside MioAgent are forbidden.
    def outside_entries():
        return sorted(
            p.relative_to(tmp_path).as_posix()
            for p in tmp_path.rglob("*")
            if p != fake_project and fake_project not in p.parents
        )

    before = outside_entries()
    execute_owner_preview(fake_project, "Review existing Work source", ["mio/engine.py"])
    assert outside_entries() == before
