"""AUT3A state-machine acceptance, with no model calls or host code execution."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mio.autonomy_program import (
    initialize,
    read_program,
    ready_tasks,
    save_proposal,
    verify_task,
)
from mio.autonomy_supervisor import (
    approve_job,
    begin_step,
    complete_step,
    create_job,
    finalize_job,
    read_jobs,
    reconcile_interrupted,
    resume_job,
)

BASE = "364fe4fb5ddb5f341abf084961a810335653e1b5"
PROPOSAL = [
    "Review the approved task acceptance and collect unchanged source inputs",
    "Run independent acceptance tests in an isolated environment",
    "Compare results and inspect a reviewer-approved evidence digest",
]


def store(tmp_path: Path) -> Path:
    dest = tmp_path / "autonomy"
    initialize(dest, BASE)
    return dest


def test_old_backlog_remains_compatible(tmp_path):
    dest = store(tmp_path)
    program = read_program(dest)
    assert program["schema"] == 1
    assert [x["id"] for x in ready_tasks(program)] == ["ui-live", "model-eval"]
    assert all(not t["verified_by_owner"] for t in program["tasks"])


def _report(dest: Path) -> str:
    reports = dest / "reports"
    reports.mkdir(mode=0o700)
    models = [{"name": model, "digest": "1" * 64}
              for model in ("gpt-oss:20b", "qwen3.5:9b", "qwen3.8:27b")]
    body = {"schema": 1, "cloud_calls": False, "model_downloads": False,
            "role_policy_modified": False, "models": models, "results": [
                {"passed": True, "role": role, "model": model["name"]}
                for model in models for role in ("planning", "coding", "writing", "research")
            ]}
    raw = (json.dumps(body) + "\n").encode()
    digest = hashlib.sha256(raw).hexdigest()
    path = reports / (digest + ".json")
    path.write_bytes(raw)
    path.chmod(0o600)
    return digest


def test_no_implicit_owner_approval(tmp_path):
    dest = store(tmp_path)
    with pytest.raises(ValueError, match="owner confirmation"):
        verify_task(dest, "model-eval", "a" * 64, "Personally reviewed", owner_confirmed=False)
    assert not any(t["verified_by_owner"] for t in read_program(dest)["tasks"])


def test_report_digest_must_exist(tmp_path):
    dest = store(tmp_path)
    with pytest.raises(FileNotFoundError):
        verify_task(dest, "model-eval", "a" * 64, "Personally reviewed", owner_confirmed=True)


def test_report_digest_must_match_bytes(tmp_path):
    dest = store(tmp_path)
    digest = _report(dest)
    (dest / "reports" / (digest + ".json")).write_text("{}")
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        verify_task(dest, "model-eval", digest, "Personally reviewed", owner_confirmed=True)


def test_report_cannot_claim_cloud_use(tmp_path):
    dest = store(tmp_path)
    path = dest / "reports"
    path.mkdir(mode=0o700)
    raw = json.dumps({"schema": 1, "cloud_calls": True, "model_downloads": False,
                      "role_policy_modified": False, "results": [{"passed": True}] * 4}).encode()
    digest = hashlib.sha256(raw).hexdigest()
    (path / (digest + ".json")).write_bytes(raw)
    (path / (digest + ".json")).chmod(0o600)
    with pytest.raises(RuntimeError, match="valid local model"):
        verify_task(dest, "model-eval", digest, "Personally reviewed", owner_confirmed=True)


def test_verify_unlocks_dependency_without_auto_execution(tmp_path):
    dest = store(tmp_path)
    digest = _report(dest)
    result = verify_task(dest, "model-eval", digest, "Reviewed local evaluation and logs",
                         owner_confirmed=True)
    assert result["state"] == "verified" and result["verified_by_owner"] is True
    assert "supervisor-jobs" in [x["id"] for x in ready_tasks(read_program(dest))]
    assert read_jobs(dest) == []


def test_duplicate_approval_rejected(tmp_path):
    dest = store(tmp_path)
    digest = _report(dest)
    verify_task(dest, "model-eval", digest, "Reviewed local evaluation and logs",
                owner_confirmed=True)
    with pytest.raises(RuntimeError, match="already verified"):
        verify_task(dest, "model-eval", digest, "Reviewed local evaluation and logs",
                    owner_confirmed=True)


def test_cannot_verify_blocked_task(tmp_path):
    dest = store(tmp_path)
    with pytest.raises(RuntimeError, match="dependencies"):
        verify_task(dest, "repo-runner", "a" * 64, "I reviewed completed runner tests",
                    owner_confirmed=True)


def _job(dest: Path) -> dict:
    save_proposal(dest, "ui-live", PROPOSAL, "gpt-oss:20b")
    return create_job(dest, "ui-live")


def test_create_job_requires_proposal(tmp_path):
    dest = store(tmp_path)
    with pytest.raises(RuntimeError, match="existing planning proposal"):
        create_job(dest, "ui-live")


def test_untrusted_proposal_cannot_execute_without_approval(tmp_path):
    dest = store(tmp_path)
    job = _job(dest)
    assert job["state"] == "awaiting_approval"
    with pytest.raises(RuntimeError, match="not eligible"):
        begin_step(dest, job["id"], 0)
    assert all(s["state"] == "pending" for s in read_jobs(dest)[0]["steps"])


def test_approve_requires_digest_and_owner(tmp_path):
    dest = store(tmp_path)
    job = _job(dest)
    with pytest.raises(ValueError, match="owner approval"):
        approve_job(dest, job["id"], job["plan_sha256"])
    with pytest.raises(RuntimeError, match="does not match"):
        approve_job(dest, job["id"], "f" * 64, owner_confirmed=True)
    approved = approve_job(dest, job["id"], job["plan_sha256"], owner_confirmed=True)
    assert approved["state"] == "approved"
    assert any(e["action"] == "owner_approved" for e in approved["events"])


def test_steps_enforce_order_and_fingerprints(tmp_path):
    dest = store(tmp_path)
    job = _job(dest)
    approve_job(dest, job["id"], job["plan_sha256"], owner_confirmed=True)
    with pytest.raises(RuntimeError, match="Earlier steps"):
        begin_step(dest, job["id"], 1)
    begin_step(dest, job["id"], 0)
    with pytest.raises(ValueError, match="SHA256 evidence"):
        complete_step(dest, job["id"], 0, "bad")
    result = complete_step(dest, job["id"], 0, "1" * 64)
    assert result["state"] == "approved"
    assert result["steps"][0]["evidence_sha256"] == "1" * 64


def test_reconcile_marks_not_completed_and_resume_gated(tmp_path):
    dest = store(tmp_path)
    job = _job(dest)
    approve_job(dest, job["id"], job["plan_sha256"], owner_confirmed=True)
    begin_step(dest, job["id"], 0)
    assert reconcile_interrupted(dest) == 1
    assert reconcile_interrupted(dest) == 0
    current = read_jobs(dest)[0]
    assert current["state"] == "interrupted"
    assert current["steps"][0]["state"] == "pending"
    with pytest.raises(ValueError, match="Owner"):
        resume_job(dest, job["id"])
    assert resume_job(dest, job["id"], owner_confirmed=True)["state"] == "approved"


def test_finish_needs_independent_owner_milestone_verification(tmp_path):
    dest = store(tmp_path)
    job = _job(dest)
    approve_job(dest, job["id"], job["plan_sha256"], owner_confirmed=True)
    for index in range(len(PROPOSAL)):
        begin_step(dest, job["id"], index)
        complete_step(dest, job["id"], index, str(index) * 64)
    assert read_jobs(dest)[0]["state"] == "needs_review"
    with pytest.raises(RuntimeError, match="owner milestone verification"):
        finalize_job(dest, job["id"], owner_confirmed=True)
    verify_task(dest, "ui-live", "e" * 64, "I reviewed interactive browser acceptance",
                owner_confirmed=True)
    assert finalize_job(dest, job["id"], owner_confirmed=True)["state"] == "completed"


def test_untrusted_job_ledger_symlink_refused(tmp_path):
    dest = store(tmp_path)
    secret = tmp_path / "different-file"
    secret.write_text("{}")
    (dest / "supervisor.json").symlink_to(secret)
    with pytest.raises(RuntimeError):
        read_jobs(dest)


def test_job_plan_tampering_is_detected(tmp_path):
    dest = store(tmp_path)
    _job(dest)
    path = dest / "supervisor.json"
    ledger = json.loads(path.read_text())
    ledger["jobs"][0]["steps"][0]["text"] = "Run arbitrary dangerous shell command"
    path.write_text(json.dumps(ledger))
    with pytest.raises(RuntimeError, match="integrity"):
        read_jobs(dest)


def test_private_permissions(tmp_path):
    dest = store(tmp_path)
    job = _job(dest)
    path = dest / "supervisor.json"
    assert path.stat().st_mode & 0o077 == 0
    assert job["state"] == "awaiting_approval"


def test_owner_evidence_durable_across_reads(tmp_path):
    dest = store(tmp_path)
    digest = _report(dest)
    verify_task(dest, "model-eval", digest, "Verified digest and role scores",
                owner_confirmed=True)
    reloaded = read_program(dest)
    task = next(t for t in reloaded["tasks"] if t["id"] == "model-eval")
    assert task["verification"]["artifact_sha256"] == digest
    assert task["state"] == "verified"
    assert reloaded["base_commit"] == BASE
