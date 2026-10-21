"""Reproducible, owner-triggered multi-scenario engineering benchmarks.

Fixtures and unchanged acceptance tests are private. Only the existing
repo-engineering model runner can create candidates; its Bubblewrap verifier is
responsible for running tests. This module never applies source patches.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import time
import uuid
from pathlib import Path

from mio.autonomy_program import _secure_directory

SUITE_SCHEMA = 1
SUITE_VERSION = "aut4a-python-v1"
MAX_FILE_BYTES = 24_000
CASE_IDS = ("invoice", "records", "bounded-input")
CAMPAIGN_ID = re.compile(r"[0-9a-f]{32}\Z")

# The tests are controlled fixture data, not model-created material.
CASES = {
    "invoice": {
        "task": (
            "Repair the invoice arithmetic in billing.py and fees.py. Calculate "
            "line totals from (quantity, unit_price) pairs, apply discount_pct "
            "before tax, compute tax_pct as a percentage, and charge a five-unit "
            "shipping fee only when the discounted subtotal is below 100. "
            "Return a rounded two-decimal total. Match the trusted tests."
        ),
        "files": {
            "billing.py": '''from fees import shipping_fee, tax_due


def invoice_total(lines, discount_pct, tax_pct):
    subtotal = sum(quantity * unit_price for quantity, unit_price in lines)
    discounted = subtotal - discount_pct
    return round(discounted + tax_due(subtotal, tax_pct) + shipping_fee(subtotal), 2)
''',
            "fees.py": '''def shipping_fee(subtotal):
    return 5


def tax_due(subtotal, tax_pct):
    return subtotal * tax_pct
''',
            "test_billing.py": '''import unittest
from billing import invoice_total


class InvoiceTests(unittest.TestCase):
    def test_discount_then_tax(self):
        self.assertEqual(invoice_total([(2, 50)], 10, 10), 104.0)

    def test_free_shipping_threshold(self):
        self.assertEqual(invoice_total([(1, 125)], 20, 0), 100.0)

    def test_below_threshold_shipping(self):
        self.assertEqual(invoice_total([(1, 99)], 0, 0), 104.0)

    def test_multiple_lines(self):
        self.assertEqual(invoice_total([(2, 12.5), (3, 10)], 0, 10), 65.5)

    def test_discount_affects_shipping(self):
        self.assertEqual(invoice_total([(1, 100)], 1, 0), 104.0)
''',
            "test_fees.py": '''import unittest
from fees import shipping_fee, tax_due


class FeeTests(unittest.TestCase):
    def test_tax_percentage(self):
        self.assertEqual(tax_due(80, 10), 8.0)

    def test_no_tax(self):
        self.assertEqual(tax_due(45, 0), 0.0)

    def test_free_shipping(self):
        self.assertEqual(shipping_fee(100), 0)

    def test_small_shipping(self):
        self.assertEqual(shipping_fee(99.99), 5)
''',
        },
        "editable": ("billing.py", "fees.py"),
        "tests": ("test_billing.py", "test_fees.py"),
        "minimum_tests": 9,
    },
    "records": {
        "task": (
            "Repair the records.py summarize function. Given dictionaries with "
            "category and amount, strip whitespace and casefold category names, "
            "sum repeated amounts, ignore rows whose category is missing or "
            "empty, and return a dictionary with sorted lowercase keys. "
            "Follow the independent unittest acceptance file."
        ),
        "files": {
            "records.py": '''def summarize(rows):
    output = {}
    for row in rows:
        output[row["category"]] = row["amount"]
    return output
''',
            "test_records.py": '''import unittest
from records import summarize


class RecordTests(unittest.TestCase):
    def test_combines_case_and_spaces(self):
        self.assertEqual(summarize([{"category": " Food ", "amount": 5},
                                    {"category": "food", "amount": 7}]), {"food": 12})

    def test_skips_missing_or_empty(self):
        self.assertEqual(summarize([{"amount": 99},
                                    {"category": " ", "amount": 8},
                                    {"category": "X", "amount": 2}]), {"x": 2})

    def test_empty_input(self):
        self.assertEqual(summarize([]), {})

    def test_sorts_keys(self):
        self.assertEqual(list(summarize([{"category": "z", "amount": 4},
                                         {"category": "a", "amount": 3}]).keys()), ["a", "z"])

    def test_does_not_change_input(self):
        rows = [{"category": " ABC ", "amount": 7}]
        summarize(rows)
        self.assertEqual(rows[0]["category"], " ABC ")
''',
        },
        "editable": ("records.py",),
        "tests": ("test_records.py",),
        "minimum_tests": 5,
    },
    "bounded-input": {
        "task": (
            "Implement parse_port in ports.py. It should accept integer values "
            "or decimal-digit strings with surrounding whitespace, require "
            "a range from 1 through 65535, and reject booleans, floats, "
            "signed strings, hexadecimal, empty strings and other values "
            "with ValueError. Follow the supplied immutable tests."
        ),
        "files": {
            "ports.py": '''def parse_port(value):
    return int(value)
''',
            "test_ports.py": '''import unittest
from ports import parse_port


class PortTests(unittest.TestCase):
    def test_normal_integer(self):
        self.assertEqual(parse_port(443), 443)

    def test_string_with_whitespace(self):
        self.assertEqual(parse_port(" 8080 "), 8080)

    def test_valid_edges(self):
        self.assertEqual(parse_port(1), 1)
        self.assertEqual(parse_port("65535"), 65535)

    def test_rejects_invalid_types(self):
        for item in (True, False, 2.5, None, [80]):
            with self.subTest(item=item), self.assertRaises(ValueError):
                parse_port(item)

    def test_rejects_out_of_range(self):
        for item in (0, 65536, -1, "70000"):
            with self.subTest(item=item), self.assertRaises(ValueError):
                parse_port(item)

    def test_rejects_invalid_strings(self):
        for item in ("", " ", "+80", "-1", "0x50", "8.0", "hello"):
            with self.subTest(item=item), self.assertRaises(ValueError):
                parse_port(item)
''',
        },
        "editable": ("ports.py",),
        "tests": ("test_ports.py",),
        "minimum_tests": 6,
    },
}


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _checked_folder(folder: Path) -> None:
    info = folder.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise RuntimeError("Benchmark folder is not owner-private")
    if folder.is_symlink():
        raise RuntimeError("Symlink benchmark folder refused")


def _checked_file(path: Path, limit: int = MAX_FILE_BYTES) -> bytes:
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > limit):
        raise RuntimeError("Benchmark file is unsafe or oversized")
    return path.read_bytes()


def _write_new(path: Path, data: bytes) -> None:
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("Benchmark artifact exceeds byte limit")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def bench_root(store: Path) -> Path:
    _secure_directory(store)
    root = store / "engineering-benchmarks"
    if root.is_symlink():
        raise RuntimeError("Symlink benchmark root refused")
    root.mkdir(mode=0o700, exist_ok=True)
    _checked_folder(root)
    return root


def create_campaign(store: Path, base_commit: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", base_commit):
        raise ValueError("A pinned 40-character Git checkpoint is required")
    root = bench_root(store)
    identity = uuid.uuid4().hex
    campaign = root / identity
    campaign.mkdir(mode=0o700)
    result = {"schema": SUITE_SCHEMA, "suite": SUITE_VERSION,
              "id": identity, "base_commit": base_commit,
              "created_unix": int(time.time()), "cases": {}}
    for name in CASE_IDS:
        case = CASES[name]
        dest = campaign / name
        dest.mkdir(mode=0o700)
        digests = {}
        for filename, text in case["files"].items():
            raw = text.encode("utf-8")
            _write_new(dest / filename, raw)
            digests[filename] = _hash(raw)
        result["cases"][name] = {"file_sha256": digests,
                                 "editable": list(case["editable"]),
                                 "acceptance_tests": list(case["tests"]),
                                 "minimum_tests": case["minimum_tests"]}
    _write_new(campaign / "manifest.json", (json.dumps(result, sort_keys=True, indent=2) + "\n").encode())
    return result


def load_campaign(store: Path, identity: str) -> tuple[Path, dict]:
    if not isinstance(identity, str) or not CAMPAIGN_ID.fullmatch(identity):
        raise ValueError("Invalid campaign ID")
    root = bench_root(store)
    folder = root / identity
    _checked_folder(folder)
    manifest = json.loads(_checked_file(folder / "manifest.json"))
    if (not isinstance(manifest, dict) or manifest.get("schema") != SUITE_SCHEMA
            or manifest.get("suite") != SUITE_VERSION or manifest.get("id") != identity
            or not isinstance(manifest.get("base_commit"), str)
            or not re.fullmatch(r"[0-9a-f]{40}", manifest["base_commit"])
            or not isinstance(manifest.get("cases"), dict)
            or set(manifest["cases"]) != set(CASE_IDS)):
        raise RuntimeError("Untrusted or outdated benchmark manifest")
    for name in CASE_IDS:
        dest = folder / name
        _checked_folder(dest)
        info = manifest["cases"][name]
        expected = CASES[name]
        if (not isinstance(info, dict)
                or info.get("editable") != list(expected["editable"])
                or info.get("acceptance_tests") != list(expected["tests"])
                or info.get("minimum_tests") != expected["minimum_tests"]
                or not isinstance(info.get("file_sha256"), dict)
                or set(info["file_sha256"]) != set(expected["files"])):
            raise RuntimeError("Benchmark fixture allowlist has changed")
        for filename, expected_hash in info["file_sha256"].items():
            if (not isinstance(expected_hash, str)
                    or expected_hash != _hash(expected["files"][filename].encode())
                    or _hash(_checked_file(dest / filename)) != expected_hash):
                raise RuntimeError("Benchmark fixture source or tests were changed")
    return folder, manifest


def status_campaign(store: Path, identity: str) -> dict:
    folder, manifest = load_campaign(store, identity)
    cases = {}
    for name in CASE_IDS:
        path = folder / (name + ".result.json")
        if path.exists() or path.is_symlink():
            value = json.loads(_checked_file(path, 30_000))
            if (not isinstance(value, dict) or value.get("case") != name
                    or value.get("campaign") != identity
                    or value.get("state") not in {"passed", "failed", "stopped"}):
                raise RuntimeError("Invalid campaign result record")
            if value["state"] == "passed":
                goal_id = value.get("goal_sha256")
                if not isinstance(goal_id, str) or not re.fullmatch(r"[0-9a-f]{64}", goal_id):
                    raise RuntimeError("Passed benchmark has no valid goal fingerprint")
                saved = store.parent / "repo-engineering" / goal_id
                report_hash = value.get("report_sha256")
                patch_hash = value.get("patch_sha256")
                if (not isinstance(report_hash, str) or not isinstance(patch_hash, str)
                        or _hash(_checked_file(saved / "report.json", 150_000)) != report_hash
                        or _hash(_checked_file(saved / "changes.patch", 150_000)) != patch_hash):
                    raise RuntimeError("Passed benchmark report or patch integrity failed")
            cases[name] = {"state": value["state"],
                           "attempts": value.get("attempts", 0),
                           "tests_run": value.get("tests_run", 0),
                           "patch_sha256": value.get("patch_sha256")}
        else:
            cases[name] = {"state": "pending", "attempts": 0, "tests_run": 0,
                           "patch_sha256": None}
    return {"campaign": identity, "base_commit": manifest["base_commit"],
            "suite": SUITE_VERSION, "cases": cases}


def _goal(folder: Path, name: str) -> dict:
    from mio.repo_agent import RepoGoal

    case = CASES[name]
    return RepoGoal.parse({"repository": str(folder / name), "task": case["task"],
                           "editable_files": list(case["editable"]),
                           "acceptance_tests": list(case["tests"]),
                           "max_attempts": 3})


async def run_case(store: Path, identity: str, name: str) -> dict:
    """Explicit model run; no automatic patch application or supervisor completion."""
    if name not in CASES:
        raise ValueError("Unknown benchmark scenario")
    folder, _ = load_campaign(store, identity)
    result_path = folder / (name + ".result.json")
    if result_path.exists() or result_path.is_symlink():
        raise RuntimeError("Scenario already attempted; review recorded result")
    from scripts.repo_engineer import run

    goal = _goal(folder, name)
    pre = {p: _hash(_checked_file(folder / name / p)) for p in CASES[name]["files"]}
    # Guard against concurrent/replayed model runs before inference starts.
    marker = folder / (name + ".running")
    _write_new(marker, b"started\n")
    try:
        report = await run(goal, apply=False, plan_only=False)
        success = (report.get("state") == "passed" and "applied" not in report
                   and type(report.get("tests_run")) is int
                   and report["tests_run"] >= CASES[name]["minimum_tests"])
        report_path_actual = store.parent / "repo-engineering" / goal.digest() / "report.json"
        patch_path = store.parent / "repo-engineering" / goal.digest() / "changes.patch"
        if success:
            saved = json.loads(_checked_file(report_path_actual, 150_000))
            if (not isinstance(saved, dict) or saved.get("state") != "passed"
                    or saved.get("goal_sha256") != goal.digest()
                    or saved.get("tests_run") != report["tests_run"]
                    or "applied" in saved
                    or not isinstance(saved.get("attempts"), list)
                    or not saved["attempts"]
                    or saved["attempts"][-1].get("outcome") != "passed"):
                raise RuntimeError("Trusted engineering report did not confirm passing tests")
            _checked_file(patch_path, 150_000)
        result = {"campaign": identity, "case": name,
                  "state": "passed" if success else "failed",
                  "tests_run": report.get("tests_run", 0),
                  "attempts": len(report.get("attempts", [])),
                  "report_sha256": _hash(_checked_file(report_path_actual, 150_000))
                  if report_path_actual.exists() else None,
                  "patch_sha256": _hash(_checked_file(patch_path, 150_000))
                  if success and patch_path.exists() else None,
                  "model": report.get("model"), "goal_sha256": goal.digest(),
                  "generated_patch_applied": False,
                  "reason": str(report.get("reason", ""))[:180]}
    except Exception as exc:  # noqa: BLE001 - durable failure receipt, no source patch
        result = {"campaign": identity, "case": name, "state": "stopped",
                  "tests_run": 0, "attempts": 0, "report_sha256": None,
                  "patch_sha256": None, "model": None,
                  "goal_sha256": goal.digest(),
                  "generated_patch_applied": False,
                  "reason": type(exc).__name__}
    after = {p: _hash(_checked_file(folder / name / p)) for p in CASES[name]["files"]}
    if pre != after:
        raise RuntimeError("Original benchmark source or trusted tests changed")
    _write_new(result_path, (json.dumps(result, sort_keys=True, indent=2) + "\n").encode())
    return result
