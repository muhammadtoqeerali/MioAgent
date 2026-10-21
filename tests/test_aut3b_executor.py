"""AUT3B offline acceptance: frozen owner grants, evidence, crashes, no auto-apply."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import types
from types import SimpleNamespace

import pytest

from mio.autonomy_executor import (
    _goal,
    _record_path,
    inspect_binding,
    run_approved_step,
    verified_patch_evidence,
)
from mio.autonomy_program import initialize, read_program, save_proposal, verify_task
from mio.autonomy_supervisor import approve_job, create_job, read_jobs

BASE = "f0e7e82bc2d39ea71a1de1d677c7d8cac4ff1ff9"
GOAL = "a" * 64
PROPOSAL = [
    "Inspect the trusted source contract and independently supplied acceptance tests",
    "Create a bounded Python patch and execute its frozen isolated test suite",
    "Review the test log, source diff and final evidence checksum before approval",
]


def _prepare(tmp_path):
    store = tmp_path / "autonomy"
    initialize(store, BASE)
    reports = store / "reports"
    reports.mkdir(mode=0o700)
    models = [{"name": n, "digest": "b" * 64}
              for n in ("gpt-oss:20b", "qwen3.5:9b", "qwen3.8:27b")]
    data = {"schema": 1, "cloud_calls": False, "model_downloads": False,
            "role_policy_modified": False, "models": models, "results": [
                {"passed": True, "role": role, "model": m["name"]}
                for m in models for role in ("planning", "coding", "writing", "research")
            ]}
    raw = (json.dumps(data) + "\n").encode()
    digest = hashlib.sha256(raw).hexdigest()
    (reports / f"{digest}.json").write_bytes(raw)
    (reports / f"{digest}.json").chmod(0o600)
    verify_task(store, "model-eval", digest, "Owner reviewed independent model probe report",
                owner_confirmed=True)
    verify_task(store, "supervisor-jobs", "c" * 64, "Owner reviewed supervisor state and crash tests",
                owner_confirmed=True)
    save_proposal(store, "repo-runner", PROPOSAL, "gpt-oss:20b")
    job = create_job(store, "repo-runner")
    approve_job(store, job["id"], job["plan_sha256"], owner_confirmed=True)
    return store, job


def _stub_goal(monkeypatch, tmp_path):
    goal = SimpleNamespace(root=tmp_path, editable=("calculator.py",),
                           tests=("test_calculator.py",), max_attempts=2,
                           digest=lambda: GOAL)
    module = types.ModuleType("mio.dashboard_jobs")
    module.approved_goal = lambda identity: (goal, {"id": identity})
    monkeypatch.setitem(sys.modules, "mio.dashboard_jobs", module)
    return goal


def _stub_runner(monkeypatch, tmp_path, *, failure=False, invalid=False):
    native = types.ModuleType("scripts.native_runtime")
    native.RUNTIME = tmp_path / "runtime"
    monkeypatch.setitem(sys.modules, "scripts.native_runtime", native)
    repo = types.ModuleType("scripts.repo_engineer")

    async def run(goal, *, apply, plan_only):
        assert apply is False and plan_only is False
        if failure:
            raise RuntimeError("Model or sandbox unavailable")
        folder = native.RUNTIME / "repo-engineering" / goal.digest()
        folder.mkdir(parents=True, mode=0o700)
        patch = folder / "changes.patch"
        patch.write_text("--- a/calculator.py\n+++ b/calculator.py\n+return 2\n")
        patch.chmod(0o600)
        result = {"state": "passed", "goal_sha256": goal.digest(),
                  "tests_run": 0 if invalid else 2, "patch": str(patch),
                  "attempts": [{"attempt": 1, "outcome": "passed",
                                "changed_files": ["calculator.py"]}]}
        (folder / "report.json").write_text(json.dumps(result, indent=2) + "\n")
        (folder / "report.json").chmod(0o600)
        return result

    repo.run = run
    monkeypatch.setitem(sys.modules, "scripts.repo_engineer", repo)


def test_preview_requires_frozen_owner_plan(tmp_path, monkeypatch):
    store, job = _prepare(tmp_path)
    _stub_goal(monkeypatch, tmp_path)
    preview = inspect_binding(store, job["id"], 0, GOAL, job["plan_sha256"])
    assert preview["capability"] == "private_python_patch_and_bubblewrap_tests_only"
    assert preview["acceptance_tests"] == ["test_calculator.py"]
    assert not list(store.glob("aut3b-*.json"))
    with pytest.raises(RuntimeError, match="matching frozen"):
        inspect_binding(store, job["id"], 0, GOAL, "f" * 64)
    with pytest.raises(ValueError, match="invalid"):
        inspect_binding(store, job["id"], True, GOAL, job["plan_sha256"])


def test_missing_owner_grant_cannot_start(tmp_path, monkeypatch):
    store, job = _prepare(tmp_path)
    _stub_goal(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="Explicit owner approval"):
        asyncio.run(run_approved_step(store, job["id"], 0, GOAL, job["plan_sha256"]))
    assert read_jobs(store)[0]["state"] == "approved"
    assert not list(store.glob("aut3b-*.json"))


def test_missing_registered_goal_rejected(tmp_path, monkeypatch):
    store, _ = _prepare(tmp_path)
    _stub_goal(monkeypatch, tmp_path)
    with pytest.raises(ValueError):
        _goal("bad")
    with pytest.raises(RuntimeError, match="fingerprint mismatch"):
        _goal("f" * 64)
    assert read_jobs(store)[0]["state"] == "approved"


def test_success_attaches_verified_report_without_application(tmp_path, monkeypatch):
    store, job = _prepare(tmp_path)
    _stub_goal(monkeypatch, tmp_path)
    _stub_runner(monkeypatch, tmp_path)
    result = asyncio.run(run_approved_step(
        store, job["id"], 0, GOAL, job["plan_sha256"], owner_confirmed=True))
    assert result["state"] == "needs_owner_review"
    assert result["tests_run"] == 2
    assert result["source_applied"] is False and result["git_published"] is False
    ledger = read_jobs(store)[0]
    assert ledger["steps"][0]["state"] == "verified"
    assert ledger["steps"][0]["evidence_sha256"] == result["report_sha256"]
    assert ledger["steps"][1]["state"] == "pending"
    assert ledger["state"] == "approved"
    record = _record_path(store, job["id"], 0, GOAL)
    data = json.loads(record.read_text())
    assert data["state"] == "needs_owner_review"
    assert data["evidence"]["changed_files"] == ["calculator.py"]
    assert record.stat().st_mode & 0o077 == 0
    assert all(t["state"] != "verified" for t in read_program(store)["tasks"] if t["id"] == "repo-runner")


def test_run_cannot_be_replayed(tmp_path, monkeypatch):
    store, job = _prepare(tmp_path)
    _stub_goal(monkeypatch, tmp_path)
    _stub_runner(monkeypatch, tmp_path)
    asyncio.run(run_approved_step(store, job["id"], 0, GOAL, job["plan_sha256"],
                                  owner_confirmed=True))
    with pytest.raises(RuntimeError, match="not pending"):
        asyncio.run(run_approved_step(store, job["id"], 0, GOAL, job["plan_sha256"],
                                      owner_confirmed=True))


def test_failed_sandbox_interrupted_not_verified(tmp_path, monkeypatch):
    store, job = _prepare(tmp_path)
    _stub_goal(monkeypatch, tmp_path)
    _stub_runner(monkeypatch, tmp_path, failure=True)
    with pytest.raises(RuntimeError, match="Model or sandbox unavailable"):
        asyncio.run(run_approved_step(store, job["id"], 0, GOAL, job["plan_sha256"],
                                      owner_confirmed=True))
    assert read_jobs(store)[0]["state"] == "interrupted"
    assert read_jobs(store)[0]["steps"][0]["state"] == "pending"
    record = json.loads(_record_path(store, job["id"], 0, GOAL).read_text())
    assert record["state"] == "interrupted"
    assert record["source_applied"] is False


def test_fake_pass_without_tests_is_rejected(tmp_path, monkeypatch):
    store, job = _prepare(tmp_path)
    _stub_goal(monkeypatch, tmp_path)
    _stub_runner(monkeypatch, tmp_path, invalid=True)
    with pytest.raises(RuntimeError, match="did not pass trusted tests"):
        asyncio.run(run_approved_step(store, job["id"], 0, GOAL, job["plan_sha256"],
                                      owner_confirmed=True))
    assert read_jobs(store)[0]["state"] == "interrupted"


def test_unauthorized_task_rejected(tmp_path, monkeypatch):
    store, job = _prepare(tmp_path)
    _stub_goal(monkeypatch, tmp_path)
    ledger = json.loads((store / "supervisor.json").read_text())
    ledger["jobs"][0]["task"] = "ui-live"
    ledger["jobs"][0]["acceptance"] = next(t["acceptance"] for t in read_program(store)["tasks"]
                                             if t["id"] == "ui-live")
    (store / "supervisor.json").write_text(json.dumps(ledger))
    with pytest.raises(RuntimeError, match="no repository-editing capability"):
        inspect_binding(store, job["id"], 0, GOAL, job["plan_sha256"])


def test_tampered_evidence_rejected(tmp_path):
    folder = tmp_path / "run"
    folder.mkdir()
    patch = folder / "changes.patch"
    patch.write_text("patch bytes")
    patch.chmod(0o600)
    report = {"state": "passed", "goal_sha256": GOAL, "tests_run": 2,
              "patch": str(patch), "attempts": [{"outcome": "passed",
                                                  "changed_files": ["a.py"]}]}
    path = folder / "report.json"
    path.write_text(json.dumps(report))
    path.chmod(0o600)
    assert verified_patch_evidence(folder, GOAL, report)["tests_run"] == 2
    patch.chmod(0o644)
    with pytest.raises(RuntimeError, match="owner-private"):
        verified_patch_evidence(folder, GOAL, report)
    patch.chmod(0o600)
    path.write_text("{}")
    with pytest.raises(RuntimeError, match="differs"):
        verified_patch_evidence(folder, GOAL, report)


def test_immutable_evidence_does_not_approve_backlog(tmp_path, monkeypatch):
    store, job = _prepare(tmp_path)
    _stub_goal(monkeypatch, tmp_path)
    _stub_runner(monkeypatch, tmp_path)
    asyncio.run(run_approved_step(store, job["id"], 0, GOAL, job["plan_sha256"],
                                  owner_confirmed=True))
    task = next(x for x in read_program(store)["tasks"] if x["id"] == "repo-runner")
    assert task["verified_by_owner"] is False
    assert task["state"] == "awaiting_review"
