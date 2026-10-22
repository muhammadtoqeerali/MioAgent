"""Offline integrity and feasibility tests for AUT4B hidden post-repair checks."""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from mio.autonomy_benchmarks import CASE_IDS, CASES
from mio.autonomy_holdouts import (
    HOLDOUTS,
    _frozen_candidate,
    checked_file,
    holdout_status,
    verify_holdout,
)
from mio.repo_agent import diff

GOOD = {
    "invoice": {
        "billing.py": '''from fees import shipping_fee, tax_due


def invoice_total(lines, discount_pct, tax_pct):
    subtotal = sum(quantity * unit_price for quantity, unit_price in lines)
    discounted = subtotal * (1 - discount_pct / 100)
    return round(discounted + tax_due(discounted, tax_pct) + shipping_fee(discounted), 2)
''',
        "fees.py": '''def shipping_fee(subtotal):
    return 0 if subtotal >= 100 else 5


def tax_due(subtotal, tax_pct):
    return subtotal * tax_pct / 100
''',
    },
    "records": {
        "records.py": '''def summarize(rows):
    out = {}
    for item in rows:
        key = item.get("category", "").strip().casefold()
        if key:
            out[key] = out.get(key, 0) + item["amount"]
    return dict(sorted(out.items()))
''',
    },
    "bounded-input": {
        "ports.py": '''def parse_port(value):
    if isinstance(value, bool):
        raise ValueError("Boolean port")
    if isinstance(value, int):
        port = value
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped or not stripped.isdecimal():
            raise ValueError("Bad port")
        port = int(stripped)
    else:
        raise ValueError("Bad type")
    if not 1 <= port <= 65535:
        raise ValueError("Out of bounds")
    return port
''',
    },
}


def _run_test_file(tmp_path: Path, name: str, *, valid: bool) -> subprocess.CompletedProcess[str]:
    fixture = CASES[name]
    for path, source in fixture["files"].items():
        if not path.startswith("test_"):
            source = GOOD[name].get(path, source) if valid else source
        (tmp_path / path).write_text(source, encoding="utf-8")
    test_name = f"test_holdout_{name.replace('-', '_')}.py"
    (tmp_path / test_name).write_text(HOLDOUTS[name], encoding="utf-8")
    return subprocess.run([sys.executable, "-m", "unittest", "-q", test_name[:-3]],
                          cwd=tmp_path, capture_output=True, text=True, check=False, timeout=15)


@pytest.mark.parametrize("name", CASE_IDS)
def test_holdout_is_valid_unittest_and_known_correct_solution_passes(tmp_path, name):
    result = _run_test_file(tmp_path, name, valid=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("name", CASE_IDS)
def test_holdout_rejects_original_broken_source(tmp_path, name):
    result = _run_test_file(tmp_path, name, valid=False)
    assert result.returncode != 0


@pytest.mark.parametrize("name", CASE_IDS)
def test_holdout_has_at_least_five_independent_tests(name):
    tree = ast.parse(HOLDOUTS[name])
    methods = [n for node in tree.body if isinstance(node, ast.ClassDef)
               for n in node.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
    assert len(methods) >= 5
    assert set(HOLDOUTS[name].split()) != set("".join(CASES[name]["files"].values()).split())


def _fixture(tmp_path: Path, monkeypatch, name: str = "records"):
    from mio import autonomy_holdouts as module

    store = tmp_path / "runtime" / "autonomy"
    store.mkdir(parents=True, mode=0o700)
    folder = store / "engineering-benchmarks" / ("a" * 32)
    folder.mkdir(parents=True, mode=0o700)
    case = folder / name
    case.mkdir(mode=0o700)
    originals = {p: v.encode() for p, v in CASES[name]["files"].items()}
    patched = dict(originals)
    for path, content in GOOD[name].items():
        patched[path] = content.encode()
    for path, value in originals.items():
        (case / path).write_bytes(value)
        (case / path).chmod(0o600)
    goal_id = "b" * 64
    saved = store.parent / "repo-engineering" / goal_id
    saved.mkdir(parents=True, mode=0o700)
    saved.chmod(0o700)
    attempt = saved / "attempt-1"
    attempt.mkdir(mode=0o700)
    for path, value in patched.items():
        (attempt / path).write_bytes(value)
        (attempt / path).chmod(0o600)
    changed = list(GOOD[name])
    patch = diff(originals, {p: patched[p] for p in changed}).encode()
    (saved / "changes.patch").write_bytes(patch)
    (saved / "changes.patch").chmod(0o600)
    report = {"state": "passed", "goal_sha256": goal_id, "tests_run": CASES[name]["minimum_tests"],
              "attempts": [{"attempt": 1, "changed_files": changed, "outcome": "passed"}]}
    report_raw = json.dumps(report).encode()
    (saved / "report.json").write_bytes(report_raw)
    (saved / "report.json").chmod(0o600)
    receipt = {"campaign": "a" * 32, "case": name, "state": "passed",
               "goal_sha256": goal_id, "tests_run": CASES[name]["minimum_tests"],
               "generated_patch_applied": False,
               "report_sha256": hashlib.sha256(report_raw).hexdigest(),
               "patch_sha256": hashlib.sha256(patch).hexdigest()}
    (folder / f"{name}.result.json").write_text(json.dumps(receipt))
    (folder / f"{name}.result.json").chmod(0o600)
    manifest = {"cases": {name: {"file_sha256": {p: hashlib.sha256(v).hexdigest()
                                                 for p, v in originals.items()}}}}
    monkeypatch.setattr(module, "load_campaign", lambda *_: (folder, manifest))
    monkeypatch.setattr(module, "status_campaign", lambda *_: {"cases": {name: {"state": "passed"}}})
    monkeypatch.setattr(module, "_goal", lambda *_: SimpleNamespace(digest=lambda: goal_id))
    return store, folder, saved, receipt


def test_reconstruction_authenticates_patch_and_report(tmp_path, monkeypatch):
    store, _, _, receipt = _fixture(tmp_path, monkeypatch)
    actual, recovered = _frozen_candidate(store, "a" * 32, "records")
    assert actual["records.py"] == GOOD["records"]["records.py"].encode()
    assert recovered == receipt


def test_reconstruction_rejects_modified_patch(tmp_path, monkeypatch):
    store, _, saved, _ = _fixture(tmp_path, monkeypatch)
    (saved / "changes.patch").write_bytes(b"malicious alteration")
    with pytest.raises(RuntimeError, match="changed"):
        _frozen_candidate(store, "a" * 32, "records")


def test_reconstruction_rejects_modified_source_candidate(tmp_path, monkeypatch):
    store, _, saved, _ = _fixture(tmp_path, monkeypatch)
    (saved / "attempt-1" / "records.py").write_bytes(b"def summarize(rows): return {}\n")
    with pytest.raises(RuntimeError, match="patch"):
        _frozen_candidate(store, "a" * 32, "records")


def test_owner_private_file_rejects_symlink(tmp_path):
    secret = tmp_path / "secret"
    secret.write_bytes(b"value")
    link = tmp_path / "link"
    link.symlink_to(secret)
    with pytest.raises(RuntimeError):
        checked_file(link)


def test_holdout_success_writes_unapplied_evidence(tmp_path, monkeypatch):
    store, folder, _, receipt = _fixture(tmp_path, monkeypatch)
    from mio import autonomy_holdouts as module

    monkeypatch.setattr(module, "test_staged", lambda *args, **kwargs: {
        "passed": True, "selected_tests_run": True, "tests_run": 5,
        "isolation": "Bubblewrap read-only filesystem", "outcome": "passed"})
    result = verify_holdout(store, "a" * 32, "records")
    assert result["state"] == "passed"
    assert result["model_calls"] == 0
    assert result["patch_applied"] is False
    assert result["milestone_approved"] is False
    assert result["source_report_sha256"] == receipt["report_sha256"]
    assert (folder / "records.holdout.json").exists()
    assert (folder / "records" / "records.py").read_bytes() == CASES["records"]["files"]["records.py"].encode()
    with pytest.raises(RuntimeError, match="already attempted"):
        verify_holdout(store, "a" * 32, "records")


def test_holdout_failure_is_not_reported_as_passed(tmp_path, monkeypatch):
    store, _, _, _ = _fixture(tmp_path, monkeypatch)
    from mio import autonomy_holdouts as module

    monkeypatch.setattr(module, "test_staged", lambda *args, **kwargs: {
        "passed": False, "selected_tests_run": True, "tests_run": 5,
        "isolation": "Bubblewrap read-only filesystem", "outcome": "failed"})
    result = verify_holdout(store, "a" * 32, "records")
    assert result["state"] == "failed"
    assert not result["patch_applied"]


def test_holdout_bounded_results_prevent_rerun_after_interruption(tmp_path, monkeypatch):
    store, folder, _, _ = _fixture(tmp_path, monkeypatch)
    (folder / "records.holdout-started").write_text("started")
    with pytest.raises(RuntimeError, match="already attempted"):
        verify_holdout(store, "a" * 32, "records")


def test_status_returns_pending_before_holdout(tmp_path, monkeypatch):
    store, folder, _, _ = _fixture(tmp_path, monkeypatch)
    from mio import autonomy_holdouts as module

    # Override only status case IDs for this synthetic one-case fixture.
    monkeypatch.setattr(module, "CASE_IDS", ("records",))
    value = holdout_status(store, "a" * 32)
    assert value["cases"]["records"]["state"] == "pending"
    assert not (folder / "records.holdout.json").exists()
