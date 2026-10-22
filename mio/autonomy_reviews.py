"""Read-only review dossiers for authenticated AUT4A/AUT4B engineering evidence.

Owner reviews a proposed patch before any independent application decision.
This module does not invoke models, execute sandboxes, apply patches, or touch Git.
The optional seal is an immutable private evidence record, NOT approval to apply.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from mio.autonomy_benchmarks import CASE_IDS, CASES, load_campaign
from mio.autonomy_holdouts import (
    HOLDOUT_VERSION,
    HOLDOUTS,
    _frozen_candidate,
    checked_file,
    holdout_status,
)
from mio.repo_agent import diff

REVIEW_VERSION = "aut4c-owner-review-v1"
MAX_REVIEW_BYTES = 180_000
MIN_HOLDOUT = {"invoice": 6, "records": 5, "bounded-input": 6}
SEAL_NAME = "aut4c.review.json"


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, indent=2) + "\n").encode()


def _hex64(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def build_dossier(store: Path, campaign_id: str) -> dict:
    """Re-authenticate all three saved candidates AND unseen holdout receipts.

    This is descriptive evidence only: neither the holdout results nor the seal
    are an authorization to apply code, publish Git, or approve a milestone.
    """
    folder, manifest = load_campaign(store, campaign_id)
    outcomes = holdout_status(store, campaign_id)
    if outcomes.get("suite") != HOLDOUT_VERSION:
        raise RuntimeError("Unexpected holdout version")
    if set(MIN_HOLDOUT) != set(CASE_IDS):
        raise RuntimeError("Unreviewed benchmark scenario added")
    entries: dict[str, dict] = {}
    for name in CASE_IDS:
        if outcomes["cases"][name].get("state") != "passed":
            raise RuntimeError(f"{name}: independent holdout is not passed")
        candidate, receipt = _frozen_candidate(store, campaign_id, name)
        hidden = json.loads(checked_file(folder / f"{name}.holdout.json", max_bytes=16_000))
        required = MIN_HOLDOUT[name]
        if (
            hidden.get("schema") != 1
            or hidden.get("suite") != HOLDOUT_VERSION
            or hidden.get("campaign") != campaign_id
            or hidden.get("case") != name
            or hidden.get("state") != "passed"
            or hidden.get("outcome") != "passed"
            or type(hidden.get("tests_run")) is not int
            or hidden["tests_run"] < required
            or hidden.get("model_calls") != 0
            or hidden.get("patch_applied") is not False
            or hidden.get("milestone_approved") is not False
            or not isinstance(hidden.get("isolation"), str)
            or not hidden["isolation"].startswith("Bubblewrap")
            or hidden.get("holdout_sha256") != _hash(HOLDOUTS[name].encode())
            or hidden.get("patch_sha256") != receipt.get("patch_sha256")
            or hidden.get("source_report_sha256") != receipt.get("report_sha256")
        ):
            raise RuntimeError(f"{name}: holdout receipt missing trusted evidence")
        if (
            type(receipt.get("tests_run")) is not int
            or receipt["tests_run"] < CASES[name]["minimum_tests"]
            or type(receipt.get("attempts")) is not int
            or not 1 <= receipt["attempts"] <= 3
            or not _hex64(receipt.get("report_sha256"))
            or not _hex64(receipt.get("patch_sha256"))
            or not _hex64(receipt.get("goal_sha256"))
            or not isinstance(receipt.get("model"), str)
            or not receipt["model"]
        ):
            raise RuntimeError(f"{name}: invalid source-repair result")
        editable = CASES[name]["editable"]
        originals = {p: CASES[name]["files"][p].encode() for p in editable}
        changed = {p: candidate[p] for p in editable if candidate[p] != originals[p]}
        if not changed:
            raise RuntimeError(f"{name}: no actual changed source files")
        patch = diff(originals, changed)
        if not patch or _hash(patch.encode()) != receipt["patch_sha256"]:
            raise RuntimeError(f"{name}: generated diff is not the authenticated patch")
        entries[name] = {
            "state": "ready_for_owner_review",
            "model": receipt["model"],
            "attempts": receipt["attempts"],
            "trusted_tests_passed": receipt["tests_run"],
            "hidden_tests_passed": hidden["tests_run"],
            "editable_files": list(editable),
            "changed_files": sorted(changed),
            "source_sha256": {p: _hash(originals[p]) for p in editable},
            "candidate_sha256": {p: _hash(candidate[p]) for p in editable},
            "goal_sha256": receipt["goal_sha256"],
            "source_report_sha256": receipt["report_sha256"],
            "patch_sha256": receipt["patch_sha256"],
            "holdout_receipt_sha256": _hash(
                checked_file(folder / f"{name}.holdout.json", max_bytes=16_000)
            ),
            "patch": patch,
        }
    report = {
        "schema": 1,
        "suite": REVIEW_VERSION,
        "campaign": campaign_id,
        "base_commit": manifest["base_commit"],
        "status": "owner_review_required",
        "owner_approved_apply": False,
        "source_applied": False,
        "git_published": False,
        "model_calls": 0,
        "cases": entries,
    }
    if len(_canonical(report)) > MAX_REVIEW_BYTES:
        raise RuntimeError("Owner review packet exceeded budget")
    return report


def review_overview(report: dict, *, show_diffs: bool = False) -> dict:
    """Return a compact, serializable owner-view; patch content only when requested."""
    return {
        "campaign": report["campaign"],
        "base_commit": report["base_commit"],
        "status": report["status"],
        "review_sha256": _hash(_canonical(report)),
        "owner_approved_apply": False,
        "source_applied": False,
        "cases": {
            name: {
                key: value
                for key, value in item.items()
                if show_diffs or key != "patch"
            }
            for name, item in report["cases"].items()
        },
    }


def seal_review(store: Path, campaign_id: str, *, owner_acknowledged: bool = False) -> dict:
    """Exclusively seal the audit packet; this does NOT approve applying any patch."""
    if owner_acknowledged is not True:
        raise ValueError("Explicit owner acknowledgment required to store a review packet")
    folder, _ = load_campaign(store, campaign_id)
    path = folder / SEAL_NAME
    if path.exists() or path.is_symlink():
        raise RuntimeError("Review already sealed; cannot overwrite or repeat")
    report = build_dossier(store, campaign_id)
    encoded = _canonical(report)
    # O_NOFOLLOW + O_EXCL: a repeated/concurrent seal cannot overwrite evidence.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    return review_overview(report)


def verify_seal(store: Path, campaign_id: str, *, show_diffs: bool = False) -> dict:
    """Rebuild from source evidence; byte-compare to the earlier sealed record."""
    folder, _ = load_campaign(store, campaign_id)
    path = folder / SEAL_NAME
    if not path.exists() and not path.is_symlink():
        raise RuntimeError("No sealed review packet exists")
    sealed = checked_file(path, max_bytes=MAX_REVIEW_BYTES)
    fresh = build_dossier(store, campaign_id)
    if sealed != _canonical(fresh):
        raise RuntimeError("Sealed review differs from currently authenticated evidence")
    return {**review_overview(fresh, show_diffs=show_diffs), "seal_verified": True}
