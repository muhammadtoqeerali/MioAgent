"""Post-hoc, hidden-test replay of AUT4A model patches in the existing Bubblewrap verifier.

Model prompts never include these holdouts. A passing holdout is additional evidence,
not proof of correctness; no model execution, patch application or milestone approval.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from pathlib import Path

from mio.autonomy_benchmarks import CASE_IDS, CASES, _goal, load_campaign, status_campaign
from mio.repo_agent import diff, sha, staged_snapshot, test_staged

HOLDOUT_VERSION = "aut4b-holdouts-v1"
MAX_RECORD = 16000
HOLDOUTS = {
    "invoice": '''import unittest
from billing import invoice_total
from fees import shipping_fee, tax_due

class HiddenInvoiceTests(unittest.TestCase):
    def test_fractional_discount(self):
        self.assertEqual(invoice_total([(3, 20)], 12.5, 20), 68.0)
    def test_discounted_shipping_threshold(self):
        self.assertEqual(invoice_total([(2, 100)], 50, 0), 100.0)
    def test_shipping_only_below_threshold(self):
        self.assertEqual(shipping_fee(100), 0)
        self.assertEqual(shipping_fee(99.999), 5)
    def test_decimal_tax_percent(self):
        self.assertEqual(tax_due(200, 7.5), 15.0)
    def test_nontrivial_ordering(self):
        self.assertEqual(invoice_total([(2, 30), (1, 40)], 25, 8), 86.0)
    def test_rounding(self):
        self.assertEqual(invoice_total([(3, 0.99)], 0, 7), 8.18)
''',
    "records": '''import unittest
from records import summarize

class HiddenRecordTests(unittest.TestCase):
    def test_unicode_casefold(self):
        self.assertEqual(summarize([{"category": " STRASSE ", "amount": 3},
                                    {"category": "Straße", "amount": 2}]), {"strasse": 5})
    def test_repeated_zero(self):
        self.assertEqual(summarize([{"category": "a", "amount": 0},
                                    {"category": "A", "amount": 4}]), {"a": 4})
    def test_sorted_multiple_categories(self):
        out = summarize([{"category": " B ", "amount": 2},
                         {"category": "c", "amount": 3},
                         {"category": "a", "amount": 1}])
        self.assertEqual(list(out), ["a", "b", "c"])
    def test_missing_and_blank(self):
        self.assertEqual(summarize([{}, {"category": "  ", "amount": 10},
                                    {"category": "C", "amount": 5}]), {"c": 5})
    def test_no_mutation(self):
        rows = [{"category": " X ", "amount": 9}]
        self.assertEqual(summarize(rows), {"x": 9})
        self.assertEqual(rows, [{"category": " X ", "amount": 9}])
''',
    "bounded-input": '''import unittest
from ports import parse_port

class HiddenPortTests(unittest.TestCase):
    def test_zeros_and_whitespace(self):
        self.assertEqual(parse_port(" 00080 "), 80)
    def test_edges(self):
        self.assertEqual(parse_port("1"), 1)
        self.assertEqual(parse_port(65535), 65535)
    def test_boolean_rejected(self):
        for x in (True, False):
            with self.subTest(x=x), self.assertRaises(ValueError):
                parse_port(x)
    def test_float_rejected(self):
        for x in (0.0, 10.0, 42.5):
            with self.subTest(x=x), self.assertRaises(ValueError):
                parse_port(x)
    def test_signed_string_rejected(self):
        for x in ("+1", "-2", "+65535", "-0"):
            with self.subTest(x=x), self.assertRaises(ValueError):
                parse_port(x)
    def test_invalid_outside_bounds(self):
        for x in (0, -1, 65536, "65536", "0"):
            with self.subTest(x=x), self.assertRaises(ValueError):
                parse_port(x)
''',
}


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def checked_file(path: Path, *, max_bytes: int = 160000) -> bytes:
    """Require one regular, non-symlink file in the owner-private runtime."""
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or info.st_nlink != 1
            or not 0 < info.st_size <= max_bytes):
        raise RuntimeError("Unsafe or oversized private engineering evidence")
    return path.read_bytes()


def checked_dir(path: Path) -> None:
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or path.is_symlink()
            or info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise RuntimeError("Unsafe private engineering directory")


def _frozen_candidate(store: Path, identity: str, name: str) -> tuple[dict[str, bytes], dict]:
    """Reconstruct an authenticated passing candidate without trusting report assertions."""
    folder, manifest = load_campaign(store, identity)
    status = status_campaign(store, identity)
    if status["cases"][name]["state"] != "passed":
        raise RuntimeError("Original case has no verified passing model patch")
    goal = _goal(folder, name)
    receipt = json.loads(checked_file(folder / f"{name}.result.json", max_bytes=30000))
    if (receipt.get("state") != "passed" or receipt.get("generated_patch_applied") is not False
            or receipt.get("goal_sha256") != goal.digest()
            or receipt.get("tests_run", 0) < CASES[name]["minimum_tests"]):
        raise RuntimeError("Original benchmark receipt is not an unapplied passing run")
    source = store.parent / "repo-engineering" / goal.digest()
    checked_dir(source)
    report_raw = checked_file(source / "report.json")
    patch_raw = checked_file(source / "changes.patch")
    if (digest(report_raw) != receipt.get("report_sha256")
            or digest(patch_raw) != receipt.get("patch_sha256")):
        raise RuntimeError("Engineering report or patch changed")
    report = json.loads(report_raw)
    if report.get("tests_run") != receipt["tests_run"]:
        raise RuntimeError("Engineering report and receipt have different test totals")
    attempts = report.get("attempts")
    if (report.get("state") != "passed" or report.get("goal_sha256") != goal.digest()
            or "applied" in report or not isinstance(attempts, list) or not attempts):
        raise RuntimeError("No authenticated passing run")
    last = attempts[-1]
    changed = last.get("changed_files")
    if (last.get("outcome") != "passed" or type(last.get("attempt")) is not int
            or not 1 <= last["attempt"] <= 3
            or not isinstance(changed, list) or not changed
            or len(changed) != len(set(changed))
            or not set(changed).issubset(CASES[name]["editable"])):
        raise RuntimeError("Invalid bounded coding attempt")
    candidate_dir = source / f"attempt-{last['attempt']}"
    checked_dir(candidate_dir)
    declared = manifest["cases"][name]["file_sha256"]
    if {p.name for p in candidate_dir.iterdir()} != set(declared):
        raise RuntimeError("Candidate has unexpected or missing files")
    original = {name: text.encode("utf-8") for name, text in CASES[name]["files"].items()}
    if any(digest(raw) != declared[p] for p, raw in original.items()):
        raise RuntimeError("Benchmark definition no longer matches immutable manifest")
    candidate = {p: checked_file(candidate_dir / p) for p in declared}
    changed_actual = {p for p in CASES[name]["editable"] if candidate[p] != original[p]}
    if changed_actual != set(changed):
        raise RuntimeError("Candidate differs from declared changed-files allowlist")
    if any(candidate[p] != original[p] for p in CASES[name]["tests"]):
        raise RuntimeError("Owner-supplied acceptance tests were modified")
    if diff(original, {p: candidate[p] for p in changed}).encode() != patch_raw:
        raise RuntimeError("Candidate bytes do not reproduce reviewed patch")
    return candidate, receipt


def verify_holdout(store: Path, identity: str, name: str) -> dict:
    """Run independently authored tests after inference; never apply a model patch."""
    if name not in CASE_IDS:
        raise ValueError("Unknown AUT4A case")
    folder, _ = load_campaign(store, identity)
    receipt_path = folder / f"{name}.holdout.json"
    marker = folder / f"{name}.holdout-started"
    if (receipt_path.exists() or receipt_path.is_symlink()
            or marker.exists() or marker.is_symlink()):
        raise RuntimeError("Holdout was already attempted: manual evidence review required")
    candidate, source_receipt = _frozen_candidate(store, identity, name)
    holdout_name = f"test_aut4b_holdout_{name.replace('-', '_')}.py"
    secret = HOLDOUTS[name].encode("utf-8")
    source_fingerprints = {p: sha(b) for p, b in candidate.items()}
    # Exclusive claim before test execution: repeated launches cannot overwrite evidence.
    marker_fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(marker_fd, "wb") as f:
        f.write((HOLDOUT_VERSION + "\n").encode())
    staging = folder / f"holdout-stage-{name}"
    staged_snapshot(staging, {**candidate, holdout_name: secret})
    result = test_staged(staging, (holdout_name,), {holdout_name: sha(secret)})
    if any(sha(checked_file(folder / name / p)) != digest(CASES[name]["files"][p].encode())
           for p in CASES[name]["files"]):
        raise RuntimeError("Original benchmark fixture changed during holdout evaluation")
    if any(sha(checked_file(staging / p)) != h for p, h in source_fingerprints.items()):
        raise RuntimeError("Holdout candidate changed during sandbox execution")
    passed = (result["passed"] and result["selected_tests_run"]
              and result["tests_run"] >= 1
              and result["isolation"].startswith("Bubblewrap"))
    record = {"schema": 1, "suite": HOLDOUT_VERSION,
              "campaign": identity, "case": name,
              "state": "passed" if passed else "failed",
              "created_unix": int(time.time()), "tests_run": result["tests_run"],
              "outcome": result["outcome"], "isolation": result["isolation"],
              "source_report_sha256": source_receipt["report_sha256"],
              "patch_sha256": source_receipt["patch_sha256"],
              "holdout_sha256": sha(secret),
              "model_calls": 0, "patch_applied": False, "milestone_approved": False}
    encoded = (json.dumps(record, sort_keys=True, indent=2) + "\n").encode()
    if len(encoded) > MAX_RECORD:
        raise RuntimeError("Oversized holdout receipt")
    fd = os.open(receipt_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(encoded)
        f.flush()
        os.fsync(f.fileno())
    return record


def holdout_status(store: Path, identity: str) -> dict:
    folder, _ = load_campaign(store, identity)
    cases = {}
    for name in CASE_IDS:
        result = folder / f"{name}.holdout.json"
        if not result.exists() and not result.is_symlink():
            cases[name] = {"state": "interrupted" if (folder / f"{name}.holdout-started").exists() else "pending"}
            continue
        record = json.loads(checked_file(result, max_bytes=MAX_RECORD))
        if (record.get("campaign") != identity or record.get("case") != name
                or record.get("suite") != HOLDOUT_VERSION or record.get("schema") != 1
                or record.get("state") not in {"passed", "failed"}
                or record.get("model_calls") != 0 or record.get("patch_applied") is not False
                or record.get("holdout_sha256") != sha(HOLDOUTS[name].encode())):
            raise RuntimeError("Invalid holdout receipt")
        # A recorded passed state is only useful if source evidence still agrees.
        _, original = _frozen_candidate(store, identity, name)
        if (record.get("source_report_sha256") != original["report_sha256"]
                or record.get("patch_sha256") != original["patch_sha256"]):
            raise RuntimeError("Holdout evidence binding changed")
        cases[name] = {"state": record["state"], "tests_run": record["tests_run"],
                       "outcome": record["outcome"], "holdout_sha256": record["holdout_sha256"]}
    return {"campaign": identity, "suite": HOLDOUT_VERSION, "cases": cases}
