"""B2B1: actual isolated file deliverables; no workstation model/GPU activity."""
from __future__ import annotations

import asyncio
import io
import json
import zipfile
from types import SimpleNamespace

import pytest

from mio import work_engineering as eng
from mio.work_core import WorkStop, create_project, create_run, run_info


def draft(*files):
    return json.dumps({"files": [{"path": n, "content": c} for n, c in files]})


def test_parse_valid_python():
    result = eng.parse_draft(draft(("calculator.py", "def calculate(op, a, b=None):\n    return a+b\n")))
    assert "calculator.py" in result


@pytest.mark.parametrize("name", ["../secrets.py", "a/b.py", ".env", "hello.sh", "_hidden.py", "bad\\x.py", "test.py/other", "x.py\x00"])
def test_never_trust_generated_paths(name):
    with pytest.raises(WorkStop):
        eng.parse_draft(draft((name, "print('hello')")))


def test_no_source_or_invalid_syntax_is_not_delivered():
    with pytest.raises(WorkStop):
        eng.parse_draft(draft(("README.md", "Only text")))
    with pytest.raises(WorkStop):
        eng.parse_draft(draft(("module.py", "def broken(:\n")))


def test_artifact_is_private_and_verified(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(eng, "_root", lambda _: root)
    run = "a" * 32
    files = {"module.py": "VALUE = 12\n"}
    recorded = eng.save_artifact(root, run, files, {"status": "not_run", "passed": False})
    assert recorded[0]["sha256"]
    meta, raw = eng.read_artifact(root, run)
    assert meta["run"] == run
    assert raw["module.py"] == b"VALUE = 12\n"
    with zipfile.ZipFile(io.BytesIO(eng.zip_artifact(root, run))) as package:
        assert package.read("module.py") == b"VALUE = 12\n"
        assert package.read("verification.json")
    with pytest.raises(WorkStop, match="already exists"):
        eng.save_artifact(root, run, files, {"status": "not_run"})
    (root / "engineering" / run / "module.py").write_bytes(b"TAMPER")
    with pytest.raises(WorkStop, match="hash mismatch"):
        eng.read_artifact(root, run)


def test_calculator_runs_only_inside_verified_sandbox(tmp_path, monkeypatch):
    folder = tmp_path / "engine"
    folder.mkdir(mode=0o700)
    argv_seen = []
    def mock_argv(where, code):
        argv_seen.append((str(where), code))
        return ["verified-bubblewrap", "--", "python"]
    def mock_run(args, *, seconds):
        assert args[0] == "verified-bubblewrap"
        if seconds == 10:
            return (0, "MIO_SANDBOX_PREFLIGHT_OK", False, False)
        return (0, "MIO_VERIFIER_TESTS_RUN=10", False, False)
    monkeypatch.setattr(eng, "sandbox_argv", mock_argv)
    monkeypatch.setattr(eng, "_bounded_run", mock_run)
    report = eng._verification({"calculator.py": "def calculate(op,a,b=None):\n return 1\n"}, True, folder)
    assert report["passed"] and report["tests_run"] == 10
    assert len(argv_seen) == 2
    assert not any(folder.iterdir())


def test_verifier_is_honest_when_sandbox_unavailable(tmp_path, monkeypatch):
    folder = tmp_path / "engine"
    folder.mkdir(mode=0o700)
    def blocked(*args, **kwargs):
        raise OSError("no isolation")
    monkeypatch.setattr(eng, "sandbox_argv", blocked)
    report = eng._verification({"calculator.py": "X=1\n"}, True, folder)
    assert not report["passed"]
    assert report["status"] == "sandbox_unavailable"
    assert report["tests_run"] == 0


def test_owner_approved_end_to_end_artifact_with_fake_model(tmp_path, monkeypatch):
    workroot = tmp_path / "private" / "work"
    workroot.parent.mkdir(mode=0o700)
    project = create_project(workroot, "Work · Calculator", "Generate tested code")
    run = create_run(workroot, project["id"], "Build a scientific calculator", engineering=True)
    assert run["mode"] == "engineering_queued"
    class FakeRouter:
        def __init__(self, _settings, role):
            assert role == "coding"
        async def complete(self, msgs, **kwargs):
            assert "calculator.py" in str(msgs)
            return SimpleNamespace(model="offline-fake-model", text=draft(
                ("calculator.py", "def calculate(op, a, b=None):\n    return a+b\n")))
    monkeypatch.setattr(eng, "FleetRouter", FakeRouter)
    monkeypatch.setattr(eng, "_verification", lambda *args: {
        "status": "passed", "passed": True, "tests_run": 10})
    result = asyncio.run(eng.execute_engineering(workroot, run["id"], object()))
    assert result["state"] == "answered" and result["mode"] == "engineering"
    assert len(eng.read_artifact(workroot, run["id"])[1]) == 1
    assert any(e["phase"] == "artifact.saved" for e in run_info(workroot, run["id"])["events"])


def test_bounded_tasks_remain_distinct(tmp_path):
    workroot = tmp_path / "private" / "work"
    workroot.parent.mkdir(mode=0o700)
    project = create_project(workroot, "Work · Research", "Summarize documents")
    result = create_run(workroot, project["id"], "Summarize a paper")
    assert result["mode"] == "pending"


def test_project_deletion_also_erases_private_engineering_files(tmp_path):
    from mio.work_core import update
    from mio.work_lifecycle import delete_project

    workroot = tmp_path / "private" / "work"
    workroot.parent.mkdir(mode=0o700)
    project = create_project(workroot, "Work · Generated Code", "Owner-approved sandbox source")
    run = create_run(workroot, project["id"], "Build a calculator", engineering=True)
    eng.save_artifact(workroot, run["id"], {"calculator.py": "VALUE=1\n"},
                      {"status": "not_run", "passed": False})
    update(workroot, run["id"], "needs_review", mode="engineering", result="Draft saved")
    target = workroot / "engineering" / run["id"]
    assert target.is_dir()
    result = delete_project(workroot, project["id"])
    assert result["runs_deleted"] == 1
    assert result["artifacts_cleanup_incomplete"] == []
    assert not target.exists()
