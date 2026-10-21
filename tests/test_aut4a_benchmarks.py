"""AUT4A regression tests: immutable multi-scenario private engineering fixtures."""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
import types

import pytest

from mio.autonomy_benchmarks import (
    CASE_IDS,
    CASES,
    SUITE_VERSION,
    create_campaign,
    load_campaign,
    run_case,
    status_campaign,
)

BASE = "d2113a8aa59ab5276a36d8a931e874bae787dfdb"


@pytest.fixture
def fake_engine(monkeypatch):
    """Offline fake of the external repo runner; never calls an installed model."""
    repo_module = types.ModuleType("mio.repo_agent")
    class FakeGoal:
        def __init__(self, record):
            self.record = record
        @classmethod
        def parse(cls, record):
            return cls(record)
        def digest(self):
            return hashlib.sha256(json.dumps(self.record, sort_keys=True).encode()).hexdigest()
    repo_module.RepoGoal = FakeGoal
    runner = types.ModuleType("scripts.repo_engineer")
    async def default_run(_goal, *, apply, plan_only):
        raise AssertionError("Test must inject controlled model-run result")
    runner.run = default_run
    runner._goal_for_test = lambda root: FakeGoal.parse({
        "repository": str(root), "task": CASES["records"]["task"],
        "editable_files": ["records.py"], "acceptance_tests": ["test_records.py"],
        "max_attempts": 3,
    })
    monkeypatch.setitem(sys.modules, "mio.repo_agent", repo_module)
    monkeypatch.setitem(sys.modules, "scripts.repo_engineer", runner)
    return runner


def _prepare(tmp_path):
    folder = tmp_path / "autonomy"
    folder.mkdir(mode=0o700)
    record = create_campaign(folder, BASE)
    return folder, record["id"]


def test_suite_has_three_distinct_cases():
    assert set(CASE_IDS) == {"invoice", "records", "bounded-input"}
    assert len(CASES["invoice"]["editable"]) == 2
    assert len(CASES["invoice"]["tests"]) == 2
    assert all(case["minimum_tests"] >= 5 for case in CASES.values())


def test_create_campaign_records_private_immutable_files(tmp_path):
    store, identity = _prepare(tmp_path)
    folder, manifest = load_campaign(store, identity)
    assert manifest["suite"] == SUITE_VERSION
    assert manifest["base_commit"] == BASE
    assert stat_permissions(folder / "manifest.json") == 0
    for name in CASE_IDS:
        for filename in CASES[name]["files"]:
            assert stat_permissions(folder / name / filename) == 0
            assert (folder / name / filename).read_text() == CASES[name]["files"][filename]


def stat_permissions(path):
    return path.stat().st_mode & 0o077


def test_repeated_prepares_use_new_campaign_identity(tmp_path):
    store, identity = _prepare(tmp_path)
    again = create_campaign(store, BASE)
    assert again["id"] != identity
    assert len(list((store / "engineering-benchmarks").iterdir())) == 2


def test_status_lists_all_cases_pending(tmp_path):
    store, identity = _prepare(tmp_path)
    result = status_campaign(store, identity)
    assert result["base_commit"] == BASE
    assert all(x["state"] == "pending" for x in result["cases"].values())


def test_refuses_bad_campaign_id(tmp_path):
    store, _ = _prepare(tmp_path)
    for identity in ("../../hi", "hi", "a" * 33):
        with pytest.raises(ValueError):
            load_campaign(store, identity)


def test_rejects_fixture_edit(tmp_path):
    store, identity = _prepare(tmp_path)
    file = store / "engineering-benchmarks" / identity / "invoice" / "billing.py"
    file.write_text("print('tampered')")
    with pytest.raises(RuntimeError, match="changed"):
        load_campaign(store, identity)


def test_rejects_test_edit(tmp_path):
    store, identity = _prepare(tmp_path)
    file = store / "engineering-benchmarks" / identity / "records" / "test_records.py"
    file.write_text("import unittest\n")
    with pytest.raises(RuntimeError, match="changed"):
        load_campaign(store, identity)


def test_refuses_symlink_for_manifest(tmp_path):
    store, identity = _prepare(tmp_path)
    path = store / "engineering-benchmarks" / identity / "manifest.json"
    path.unlink()
    path.symlink_to(tmp_path / "other")
    with pytest.raises((RuntimeError, FileNotFoundError)):
        load_campaign(store, identity)


def test_rejects_unapproved_case(tmp_path):
    store, identity = _prepare(tmp_path)
    import asyncio

    with pytest.raises(ValueError, match="Unknown"):
        asyncio.run(run_case(store, identity, "unknown"))


def test_refuses_manifest_case_tampering(tmp_path):
    store, identity = _prepare(tmp_path)
    file = store / "engineering-benchmarks" / identity / "manifest.json"
    data = json.loads(file.read_text())
    data["cases"]["invoice"]["editable"] = ["test_billing.py"]
    file.write_text(json.dumps(data))
    with pytest.raises(RuntimeError, match="allowlist"):
        load_campaign(store, identity)


def test_baseline_fixture_fails_independent_tests(tmp_path):
    store, identity = _prepare(tmp_path)
    root, _ = load_campaign(store, identity)
    for case_id in CASE_IDS:
        case = CASES[case_id]
        proc = subprocess.run([sys.executable, "-m", "unittest", *(
            name[:-3] for name in case["tests"]
        )], cwd=root / case_id, capture_output=True, text=True, check=False)
        assert proc.returncode != 0, case_id


def test_independent_tests_have_expected_count(tmp_path):
    store, identity = _prepare(tmp_path)
    root, _ = load_campaign(store, identity)
    for case_id in CASE_IDS:
        case = CASES[case_id]
        proc = subprocess.run([sys.executable, "-m", "unittest", *(
            name[:-3] for name in case["tests"]
        )], cwd=root / case_id, capture_output=True, text=True, check=False)
        assert f"Ran {case['minimum_tests']} tests" in proc.stderr


def test_run_records_success_without_applying_source(tmp_path, monkeypatch, fake_engine):
    store, identity = _prepare(tmp_path)
    goal = fake_engine._goal_for_test(store / "engineering-benchmarks" / identity / "records")
    fake_report_root = store.parent / "repo-engineering" / goal.digest()
    fake_report_root.mkdir(parents=True, mode=0o700)
    (fake_report_root / "report.json").write_text(json.dumps({
        "state": "passed", "goal_sha256": goal.digest(), "tests_run": 5,
        "attempts": [{"outcome": "passed"}]
    }))
    (fake_report_root / "report.json").chmod(0o600)
    (fake_report_root / "changes.patch").write_text("patch\n")
    (fake_report_root / "changes.patch").chmod(0o600)
    async def mocked_run(_goal, *, apply, plan_only):
        assert apply is False and plan_only is False
        assert _goal.digest() == goal.digest()
        return {"state": "passed", "tests_run": 5, "attempts": [{"outcome": "passed"}],
                "model": "gpt-oss:20b"}
    monkeypatch.setattr(fake_engine, "run", mocked_run)
    item = asyncio.run(run_case(store, identity, "records"))
    assert item["state"] == "passed"
    assert item["generated_patch_applied"] is False
    assert item["tests_run"] == 5
    assert len(item["patch_sha256"]) == 64
    assert status_campaign(store, identity)["cases"]["records"]["state"] == "passed"
    with pytest.raises(RuntimeError, match="already attempted"):
        asyncio.run(run_case(store, identity, "records"))


def test_run_records_failed_attempt_without_patch(tmp_path, monkeypatch, fake_engine):
    store, identity = _prepare(tmp_path)
    async def mocked_run(_goal, *, apply, plan_only):
        return {"state": "failed", "attempts": [{"outcome": "tests_failed"}],
                "reason": "unmet acceptance"}
    monkeypatch.setattr(fake_engine, "run", mocked_run)
    item = asyncio.run(run_case(store, identity, "bounded-input"))
    assert item["state"] == "failed"
    assert item["patch_sha256"] is None
    assert status_campaign(store, identity)["cases"]["bounded-input"]["state"] == "failed"


def test_exception_produces_stopped_record(tmp_path, monkeypatch, fake_engine):
    store, identity = _prepare(tmp_path)
    async def failed(_goal, *, apply, plan_only):
        raise RuntimeError("sandbox not available")
    monkeypatch.setattr(fake_engine, "run", failed)
    result = asyncio.run(run_case(store, identity, "records"))
    assert result["state"] == "stopped"
    assert result["reason"] == "RuntimeError"
    assert status_campaign(store, identity)["cases"]["records"]["state"] == "stopped"


def test_no_implicit_backlog_write(tmp_path):
    store, identity = _prepare(tmp_path)
    assert not (store / "program.json").exists()
    assert not (store / "supervisor.json").exists()
    assert status_campaign(store, identity)["campaign"] == identity


def test_refuses_bad_git_hash(tmp_path):
    store = tmp_path / "autonomy"
    store.mkdir(mode=0o700)
    with pytest.raises(ValueError):
        create_campaign(store, "bad")
