"""v0.4E repository agent: strong input isolation, exact test provenance and bounded edits."""

import asyncio
import json
from pathlib import Path

import pytest

from mio import repo_agent as agent
from mio.llm import Completion
from scripts import repo_engineer as cli


@pytest.fixture
def sample(tmp_path):
    root = tmp_path / "existing-repo"
    root.mkdir()
    (root / "calculator.py").write_text("def add(a, b):\n    return a - b\n")
    (root / "test_calculator.py").write_text(
        "import unittest\nfrom calculator import add\n"
        "class Check(unittest.TestCase):\n"
        "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n"
    )
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("PRIVATE=NOT_FOR_MODEL")
    config = {"repository": str(root), "task": "Correct the addition implementation without changing tests.",
              "editable_files": ["calculator.py"], "acceptance_tests": ["test_calculator.py"],
              "max_attempts": 2}
    return root, config


def parse(config):
    return agent.RepoGoal.parse(config)


def test_preview_is_read_only(sample):
    root, raw = sample
    goal = parse(raw)
    before = (root / "calculator.py").read_bytes()
    preview = asyncio.run(cli.run(goal))
    assert preview["editable_files"] == ["calculator.py"]
    assert preview["acceptance_sha256"]["test_calculator.py"] == agent.sha(
        (root / "test_calculator.py").read_bytes())
    assert (root / "calculator.py").read_bytes() == before


@pytest.mark.parametrize("bad", ["../secret.py", "/etc/passwd", "abc/../../x.py", ".git/config",
                                  "src//lib.py", "x\\escape.py", "a/./b.py", "a.py\x00"])
def test_refuse_escaping_paths(bad):
    with pytest.raises(agent.RepoStop):
        agent.safe_path(bad)


def test_reject_test_edit(sample):
    _, raw = sample
    raw["editable_files"] = ["test_calculator.py"]
    raw["acceptance_tests"] = ["test_calculator.py"]
    with pytest.raises(agent.RepoStop):
        parse(raw)


def test_reject_synthetic_source_file_and_symlink(sample):
    root, raw = sample
    (root / "calculator.py").unlink()
    (root / "calculator.py").symlink_to("test_calculator.py")
    with pytest.raises(agent.RepoStop):
        parse(raw)


def test_excludes_git_and_symlink_traversal(sample):
    root, _ = sample
    outside = root.parent / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("SECRET = 'not disclosed'\n")
    (root / "linked").symlink_to(outside)
    files = agent.index_tree(root)
    assert sorted(files) == ["calculator.py", "test_calculator.py"]
    assert "PRIVATE=NOT_FOR_MODEL" not in repr(files)


def test_parse_rejects_unknown_schema_fields(sample):
    _, raw = sample
    raw["shell_command"] = "rm -rf /"
    with pytest.raises(agent.RepoStop):
        parse(raw)


@pytest.mark.parametrize("text", [
    '{"edits":[{"path":"test_calculator.py","content":"assert True"}]}',
    '{"edits":[]}',
    '{"edits":[{"path":"calculator.py","content":"def add(:"}]}',
    '{"edits":[{"path":"calculator.py","content":"pass"}],"tool":"shell"}',
    'Here is some code: ```python\npass\n```',
])
def test_model_cannot_edit_tests_or_tool_contract(sample, text):
    _, raw = sample
    with pytest.raises(agent.RepoStop):
        agent.parse_edits(text, parse(raw))


def test_valid_patch_and_diff(sample):
    root, raw = sample
    goal = parse(raw)
    snapshot, pins = agent.locked_snapshot(goal)
    edits = agent.parse_edits(json.dumps({"edits": [{"path": "calculator.py",
                         "content": "def add(a, b):\n    return a + b\n"}]}), goal)
    assert list(edits) == ["calculator.py"]
    assert "+    return a + b" in agent.diff(snapshot, edits)
    assert pins["test_calculator.py"] == agent.sha((root / "test_calculator.py").read_bytes())


def test_test_runner_requires_every_approved_file(sample, tmp_path, monkeypatch):
    _root, raw = sample
    goal = parse(raw)
    snap, pinned = agent.locked_snapshot(goal)
    stage = tmp_path / "stage"
    agent.staged_snapshot(stage, snap)
    monkeypatch.setattr(agent, "sandbox_argv", lambda root, code: [code])
    monkeypatch.setattr(agent, "_bounded_run", lambda args: (0, "MIO_VERIFIER_TESTS_RUN=5\n", False, False))
    result = agent.test_staged(stage, goal.tests, pinned)
    assert result["passed"] is False  # unrelated passing tests don't count
    monkeypatch.setattr(agent, "_bounded_run", lambda args: (
        0, "MIO_SELECTED_FILE=0:2\nMIO_VERIFIER_TESTS_RUN=2\n", False, False))
    result = agent.test_staged(stage, goal.tests, pinned)
    assert result["passed"] is True
    (stage / "test_calculator.py").write_text("def test_fake(): pass")
    with pytest.raises(agent.RepoStop, match="altered"):
        agent.test_staged(stage, goal.tests, pinned)


def test_harness_names_explicit_approved_files(sample, tmp_path, monkeypatch):
    _root, raw = sample
    raw["acceptance_tests"] = ["test_calculator.py"]
    goal = parse(raw)
    snap, pins = agent.locked_snapshot(goal)
    stage = tmp_path / "stage"
    agent.staged_snapshot(stage, snap)
    captured = []
    monkeypatch.setattr(agent, "sandbox_argv", lambda p, code: captured.append(code) or [])
    monkeypatch.setattr(agent, "_bounded_run", lambda args: (1, "", False, False))
    agent.test_staged(stage, goal.tests, pins)
    assert "('test_calculator.py',)" in captured[0]
    assert "MIO_SELECTED_FILE" in captured[0]


def test_stale_repository_source_never_overwritten(sample, tmp_path):
    root, raw = sample
    goal = parse(raw)
    snap, _ = agent.locked_snapshot(goal)
    (root / "calculator.py").write_text("# changed by human\n")
    with pytest.raises(agent.RepoStop, match="changed during verification"):
        agent.apply_verified(goal, snap, {"calculator.py": b"def add(a,b): return a+b\n"}, tmp_path)
    assert "human" in (root / "calculator.py").read_text()


def test_apply_requires_original_hash_and_preserves_backup(sample, tmp_path):
    root, raw = sample
    goal = parse(raw)
    snap, pins = agent.locked_snapshot(goal)
    original = snap["calculator.py"]
    changes = {"calculator.py": b"def add(a, b):\n    return a + b\n"}
    result = agent.apply_verified(goal, snap, changes, tmp_path)
    assert result["applied"] == ["calculator.py"]
    assert (root / "calculator.py").read_bytes() == changes["calculator.py"]
    assert (tmp_path / "original-source-backup/calculator.py").read_bytes() == original
    assert pins["test_calculator.py"] == agent.sha((root / "test_calculator.py").read_bytes())


def test_full_bounded_flow_uses_independent_fallback(sample, tmp_path, monkeypatch):
    root, raw = sample
    goal = parse(raw)
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    monkeypatch.setattr(cli, "RUNTIME", runtime)
    monkeypatch.setattr(cli, "preflight", lambda folder: {"ok": True})
    monkeypatch.setattr(cli, "load_policy", lambda: object())
    monkeypatch.setattr(cli, "_settings", lambda: object())

    calls = []

    class FakeFleet:
        def __init__(self, settings, role, policy):
            self.role = role
            self.position = 0

        async def complete(self, messages, max_tokens):
            calls.append((self.role, self.position))
            if self.role == "planning":
                return Completion('{"steps":["Inspect file","Fix add","Run tests"]}', "local", "gpt-oss:20b")
            if self.position == 0:
                return Completion('{"edits": []}', "local", "gpt-oss:20b")
            return Completion(json.dumps({"edits": [{"path": "calculator.py",
                "content": "def add(a,b):\n    return a + b\n"}]}), "local", "qwen3.8:27b")

        def advance(self):
            self.position += 1
            return self.position < 2

    monkeypatch.setattr(cli, "FleetRouter", FakeFleet)

    def fake_tests(folder, selected, pins):
        source = (folder / "calculator.py").read_text()
        return {"passed": "a + b" in source, "tests_run": 1, "selected_tests_run": True,
                "return_code": 0 if "a + b" in source else 1,
                "outcome": "passed" if "a + b" in source else "failed",
                "log": "MIO_SELECTED_FILE=0:1\nMIO_VERIFIER_TESTS_RUN=1", "isolation": "fake unit test"}

    monkeypatch.setattr(cli, "test_staged", fake_tests)
    result = asyncio.run(cli.run(goal, plan_only=False))
    assert result["state"] == "passed"
    assert result["model"] == "qwen3.8:27b"
    assert len(result["attempts"]) == 2
    assert calls == [("planning", 0), ("coding", 0), ("coding", 1)]
    assert (root / "calculator.py").read_text().find("a - b") >= 0
    assert Path(result["patch"]).exists()
    with pytest.raises(agent.RepoStop, match="run already exists"):
        asyncio.run(cli.run(goal, plan_only=False))
    # Second-stage human approval re-verifies saved bytes without more inference.
    patch_file = Path(result["patch"])
    good_patch = patch_file.read_text()
    patch_file.write_text("tampered")
    with pytest.raises(agent.RepoStop, match="patch differs"):
        cli.apply_previous(goal)
    assert "a - b" in (root / "calculator.py").read_text()
    patch_file.write_text(good_patch)
    accepted = cli.apply_previous(goal)
    assert accepted["applied"]["applied"] == ["calculator.py"]
    assert "a + b" in (root / "calculator.py").read_text()
    assert len(calls) == 3  # approval made no model calls
    with pytest.raises(agent.RepoStop, match="unapplied"):
        cli.apply_previous(goal)


def test_refuse_apply_without_execute_on_parser(monkeypatch):
    monkeypatch.setattr("sys.argv", ["repo_engineer", "fake.json", "--apply"])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2


def test_demo_is_two_module_five_test_challenge(tmp_path, monkeypatch):
    from scripts import repo_agent_demo
    monkeypatch.setattr(repo_agent_demo, "setup_runtime", lambda: None)
    monkeypatch.setattr(repo_agent_demo, "RUNTIME", tmp_path)
    repo_agent_demo.main()
    config = json.loads((tmp_path / "repo-engineering-demo-goal.json").read_text())
    assert len(config["editable_files"]) == 2
    goal = agent.RepoGoal.parse(config)
    files, _ = agent.locked_snapshot(goal)
    assert all(path in files for path in goal.tests)
    with pytest.raises(SystemExit, match="Demo already exists"):
        repo_agent_demo.main()
