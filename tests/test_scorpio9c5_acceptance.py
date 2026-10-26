"""SCORPIO9C5 acceptance: real isolated worker, never production Work state."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from mio.scorpio9c5_acceptance import (
    APPROVAL,
    CASES,
    _case_root,
    _child_environment,
    _prepare,
    _snapshot,
    _verify,
    main,
    trial,
)
from mio.work_core import WorkStop, db


@pytest.mark.parametrize("label", CASES)
def test_real_sequential_worker_and_negative_cases(tmp_path, label):
    """Uses actual subprocess Work worker, SQLite supervisor, and real Bwrap."""
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    result = trial(private, label)
    assert result["case"] == label
    if label == "sequential":
        assert result["plan_state"] == "complete"
        assert result["run_states"] == ["answered", "answered"]
        assert result["sandbox_successes"] == 2
        assert result["grant_uses"] == 2
    else:
        assert result["plan_state"] == "attention"
        assert result["run_states"] == ["needs_review"]
        assert result["sandbox_successes"] == 0
        assert result["grant_uses"] == 0


def test_child_environment_excludes_ambient_credentials(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "sensitive-token-must-not-escape")
    monkeypatch.setenv("MIO_CLOUD_API_KEY", "sensitive-cloud-key")
    monkeypatch.setenv("MIO_API_TOKEN", "production-like-secret")
    env = _child_environment()
    assert "GITHUB_TOKEN" not in env
    assert "sensitive" not in repr(env)
    assert env["MIO_ALLOW_CLOUD"] == "false"
    assert env["MIO_MODEL_ROUTE"] == "local"
    assert env["MIO_CLOUD_API_KEY"] == ""
    assert env["MIO_LOCAL_MODEL"] == ""


def test_case_root_rejects_invalid_names_and_nonprivate_parent(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    with pytest.raises(WorkStop, match="Unknown"):
        _case_root(private, "../production")
    private.chmod(0o755)
    with pytest.raises(WorkStop, match="owner-private"):
        _case_root(private, "sequential")


def test_no_cli_execution_without_explicit_approval(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["scorpio9c5", "--mode", "isolated", "--approval", "INVALID"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2


def test_verify_rejects_fake_answer_or_replayed_grant():
    fixture = {"files": {"a.txt": "0" * 64}}
    row = {"id": "1", "state": "answered", "mode": "tool_sha256",
           "result": "Verified offline SHA-256: " + "0" * 64}
    data = {"plan": "complete", "steps": [{"state": "done"}], "runs": [row, row],
            "grants": [{"used": 1}, {"used": 1}],
            "events": ["tool.claimed", "tool.claimed", "tool.verified", "tool.verified"]}
    with pytest.raises(WorkStop, match="Sequential"):
        _verify(data, fixture, "sequential")


def test_verify_rejects_denial_that_claims_execution():
    row = {"id": "1", "state": "needs_review", "mode": "tool_denied", "result": None}
    data = {"plan": "attention", "steps": [{"state": "attention"}], "runs": [row],
            "grants": [{"used": 0}], "events": ["tool.denied", "tool.claimed"]}
    with pytest.raises(WorkStop, match="Denied"):
        _verify(data, {}, "revoked")


def test_approval_phrase_is_specific():
    assert "NO PRODUCTION TASKS" in APPROVAL
    assert set(CASES) == {"sequential", "revoked", "expired", "changed", "unbound"}
    assert Path(sys.executable).is_file()


def test_unbound_snapshot_before_worker_needs_no_grant_table(tmp_path):
    """Regression: unbound plan has no table until the worker first checks it."""
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    root, base = _case_root(private, "unbound")
    fixture = _prepare(root, base, "unbound")
    sql = "SELECT 1 FROM sqlite_master WHERE type='table' AND name='scorpio9c_grants'"
    with db(root) as conn:
        assert conn.execute(sql).fetchone() is None
    snapshot = _snapshot(root, fixture["plan"])
    assert snapshot["grants"] == []
    assert snapshot["plan"] == "ready"
    with db(root) as conn:
        assert conn.execute(sql).fetchone() is None


def test_trial_does_not_mask_original_failure_during_early_worker_exit(tmp_path, monkeypatch):
    """A teardown SIGTERM before handler install must not replace an actual error."""
    from mio import scorpio9c5_acceptance as acceptance

    class Child:
        returncode = None

        def poll(self):
            return self.returncode

        def send_signal(self, number):
            self.returncode = -number

        def communicate(self, timeout=None):
            return b"", None

    def broken_snapshot(_root, _plan):
        raise WorkStop("Primary snapshot error")

    monkeypatch.setattr(acceptance.shutil, "which", lambda _name: "/usr/bin/bwrap")
    monkeypatch.setattr(acceptance, "_case_root", lambda p, _label: (p / "work", p / "inputs"))
    monkeypatch.setattr(acceptance, "_prepare", lambda *_args: {"plan": "0" * 32})
    monkeypatch.setattr(acceptance, "_spawn_worker", lambda _root: Child())
    monkeypatch.setattr(acceptance, "_snapshot", broken_snapshot)
    with pytest.raises(WorkStop, match="Primary snapshot error"):
        acceptance.trial(tmp_path, "unbound")
