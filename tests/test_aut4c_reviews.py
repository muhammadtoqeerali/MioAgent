"""AUT4C offline contract: no model, Git, patch apply or sandbox execution."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from mio import autonomy_reviews as review
from mio.autonomy_benchmarks import CASE_IDS, CASES
from mio.autonomy_holdouts import HOLDOUT_VERSION, HOLDOUTS
from mio.repo_agent import diff

CAMPAIGN = "a" * 32
BASE = "b" * 40


@pytest.fixture
def evidence(tmp_path: Path, monkeypatch):
    folder = tmp_path / "campaign"
    folder.mkdir(mode=0o700)
    manifest = {"base_commit": BASE}
    receipts = {}
    candidates = {}
    for name in CASE_IDS:
        case = CASES[name]
        original = {p: text.encode() for p, text in case["files"].items()}
        changed_path = case["editable"][0]
        candidate = {**original, changed_path: original[changed_path] + b"\n# audited\n"}
        changed = {changed_path: candidate[changed_path]}
        patch = diff({p: original[p] for p in case["editable"]}, changed)
        assert patch
        receipts[name] = {
            "state": "passed",
            "model": "approved-local-model",
            "attempts": 1,
            "tests_run": case["minimum_tests"],
            "goal_sha256": review._hash(f"goal:{name}".encode()),
            "report_sha256": review._hash(f"report:{name}".encode()),
            "patch_sha256": review._hash(patch.encode()),
        }
        candidates[name] = candidate
        holdout = {
            "schema": 1,
            "suite": HOLDOUT_VERSION,
            "campaign": CAMPAIGN,
            "case": name,
            "state": "passed",
            "outcome": "passed",
            "tests_run": review.MIN_HOLDOUT[name],
            "model_calls": 0,
            "patch_applied": False,
            "milestone_approved": False,
            "isolation": "Bubblewrap read-only filesystem, no network or GPU",
            "holdout_sha256": review._hash(HOLDOUTS[name].encode()),
            "patch_sha256": receipts[name]["patch_sha256"],
            "source_report_sha256": receipts[name]["report_sha256"],
        }
        path = folder / f"{name}.holdout.json"
        with path.open("x") as stream:
            json.dump(holdout, stream)
        path.chmod(0o600)

    status = {"suite": HOLDOUT_VERSION, "cases": {
        name: {"state": "passed"} for name in CASE_IDS
    }}
    monkeypatch.setattr(review, "load_campaign", lambda store, ident: (folder, manifest))
    monkeypatch.setattr(review, "holdout_status", lambda store, ident: status)
    monkeypatch.setattr(review, "_frozen_candidate",
                        lambda store, ident, name: (candidates[name], receipts[name]))
    return folder, receipts, candidates, status


def test_build_dossier_all_cases(evidence, tmp_path):
    folder, _, _, _ = evidence
    report = review.build_dossier(tmp_path, CAMPAIGN)
    assert report["suite"] == review.REVIEW_VERSION
    assert report["status"] == "owner_review_required"
    assert report["owner_approved_apply"] is False
    assert report["source_applied"] is False
    assert report["git_published"] is False
    assert report["model_calls"] == 0
    assert set(report["cases"]) == set(CASE_IDS)
    assert sum(v["hidden_tests_passed"] for v in report["cases"].values()) == 17
    assert sum(v["trusted_tests_passed"] for v in report["cases"].values()) == 20
    assert not (folder / review.SEAL_NAME).exists()


def test_default_overview_redacts_patches(evidence, tmp_path):
    report = review.build_dossier(tmp_path, CAMPAIGN)
    overview = review.review_overview(report)
    assert len(overview["review_sha256"]) == 64
    assert all("patch" not in x for x in overview["cases"].values())
    assert all("patch" in x for x in review.review_overview(report, show_diffs=True)["cases"].values())


def test_seal_requires_acknowledgement(evidence, tmp_path):
    with pytest.raises(ValueError, match="acknowledgment"):
        review.seal_review(tmp_path, CAMPAIGN)
    assert not (evidence[0] / review.SEAL_NAME).exists()


def test_seal_is_exclusive_and_verifiable(evidence, tmp_path):
    folder = evidence[0]
    result = review.seal_review(tmp_path, CAMPAIGN, owner_acknowledged=True)
    assert len(result["review_sha256"]) == 64
    path = folder / review.SEAL_NAME
    assert path.is_file()
    assert (path.stat().st_mode & 0o077) == 0
    assert review.verify_seal(tmp_path, CAMPAIGN)["seal_verified"] is True
    with pytest.raises(RuntimeError, match="already sealed"):
        review.seal_review(tmp_path, CAMPAIGN, owner_acknowledged=True)


def test_tampered_seal_rejected(evidence, tmp_path):
    folder = evidence[0]
    review.seal_review(tmp_path, CAMPAIGN, owner_acknowledged=True)
    path = folder / review.SEAL_NAME
    raw = path.read_bytes()
    path.write_bytes(raw.replace(b"owner_review_required", b"owner_review_accepted"))
    with pytest.raises(RuntimeError, match="differs"):
        review.verify_seal(tmp_path, CAMPAIGN)


def test_symlink_seal_rejected(evidence, tmp_path):
    folder = evidence[0]
    outside = tmp_path / "outside.txt"
    outside.write_text("protected")
    (folder / review.SEAL_NAME).symlink_to(outside)
    with pytest.raises(RuntimeError, match="already sealed"):
        review.seal_review(tmp_path, CAMPAIGN, owner_acknowledged=True)
    assert outside.read_text() == "protected"
    with pytest.raises((RuntimeError, OSError)):
        review.verify_seal(tmp_path, CAMPAIGN)


@pytest.mark.parametrize("case", CASE_IDS)
def test_failed_holdout_rejected(evidence, tmp_path, case):
    evidence[3]["cases"][case]["state"] = "failed"
    with pytest.raises(RuntimeError, match="not passed"):
        review.build_dossier(tmp_path, CAMPAIGN)


@pytest.mark.parametrize("key,value", [
    ("model_calls", 1),
    ("patch_applied", True),
    ("milestone_approved", True),
    ("isolation", "unisolated"),
    ("tests_run", 0),
    ("outcome", "failed"),
    ("state", "stopped"),
    ("source_report_sha256", "f" * 64),
    ("patch_sha256", "f" * 64),
    ("holdout_sha256", "f" * 64),
])
def test_invalid_hidden_receipt_rejected(evidence, tmp_path, key, value):
    path = evidence[0] / "invoice.holdout.json"
    record = json.loads(path.read_text())
    record[key] = value
    path.write_text(json.dumps(record))
    with pytest.raises(RuntimeError, match="receipt"):
        review.build_dossier(tmp_path, CAMPAIGN)


@pytest.mark.parametrize("key,value", [
    ("attempts", 4),
    ("attempts", True),
    ("tests_run", 0),
    ("model", ""),
    ("patch_sha256", "invalid"),
])
def test_invalid_original_receipt_rejected(evidence, tmp_path, key, value):
    evidence[1]["records"][key] = value
    with pytest.raises(RuntimeError, match="source-repair|authenticated patch|holdout receipt"):
        review.build_dossier(tmp_path, CAMPAIGN)


def test_changed_candidate_rejected(evidence, tmp_path):
    name = "records"
    path = CASES[name]["editable"][0]
    evidence[2][name][path] = b"different source"
    with pytest.raises(RuntimeError, match="authenticated patch"):
        review.build_dossier(tmp_path, CAMPAIGN)


def test_failed_holdout_cannot_seal(evidence, tmp_path):
    evidence[3]["cases"]["invoice"]["state"] = "failed"
    with pytest.raises(RuntimeError):
        review.seal_review(tmp_path, CAMPAIGN, owner_acknowledged=True)
    assert not (evidence[0] / review.SEAL_NAME).exists()


def test_overlarge_packet_rejected(evidence, tmp_path, monkeypatch):
    monkeypatch.setattr(review, "MAX_REVIEW_BYTES", 100)
    with pytest.raises(RuntimeError, match="exceeded"):
        review.build_dossier(tmp_path, CAMPAIGN)


def test_private_seal_does_not_create_commit(evidence, tmp_path):
    before = sorted(p.name for p in evidence[0].iterdir())
    review.seal_review(tmp_path, CAMPAIGN, owner_acknowledged=True)
    after = sorted(p.name for p in evidence[0].iterdir())
    assert sorted(set(after) - set(before)) == [review.SEAL_NAME]
    assert set(before) <= set(after)


def test_other_user_permission_is_not_used(evidence, tmp_path):
    path = evidence[0] / "records.holdout.json"
    os.chmod(path, 0o644)
    with pytest.raises(RuntimeError, match="[Uu]nsafe"):
        review.build_dossier(tmp_path, CAMPAIGN)
