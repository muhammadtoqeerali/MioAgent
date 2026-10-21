"""AUT1 local-only evaluation policies and deterministic probe boundaries."""

from __future__ import annotations

import json
import os
import stat

import pytest

from mio.autonomy_eval import PROBES, allowed_models, grade, write_report


@pytest.fixture
def installed():
    return {"gpt-oss:20b": {"digest": "a" * 64}, "qwen3.8:27b": {"digest": "b" * 64}}


def test_reject_nonlocal_or_uninstalled_candidates(installed):
    for names in ([], ["not-present"], ["gpt-oss:20b", "gpt-oss:20b"],
                  ["qwen3.8:27b", "bad:cloud"]):
        with pytest.raises(ValueError):
            allowed_models(names, installed)


def test_accept_explicit_installed_models(installed):
    assert allowed_models(["gpt-oss:20b", "qwen3.8:27b"], installed) == ["gpt-oss:20b", "qwen3.8:27b"]


def test_probes_are_basic_and_truthfully_scoped():
    assert set(PROBES) == {"planning", "coding", "writing", "research"}
    assert grade("research", "Study [R1] lacks a control [R2].")["score"] == 1
    assert grade("research", "Study [R1] and invented [R3].")["score"] == 0
    assert grade("coding", "def add(a,b):\n    return a+b")["score"] == 1
    assert grade("writing", "Subject: Meeting on Thursday")["score"] == 1
    assert grade("planning", json.dumps({"steps": ["A", "B", "C"]}))["score"] == 1
    with pytest.raises(ValueError):
        grade("self-improve", "Perfect")


def test_private_immutable_benchmark_report(tmp_path):
    store = tmp_path / "autonomy"
    store.mkdir(mode=0o700)
    os.chmod(store, 0o700)
    report = {"meaning": "tiny_local_format_probes_not_sota_quality", "cloud_calls": False}
    target = write_report(report, store)
    assert target.is_file()
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert json.loads(target.read_text()) == report
    with pytest.raises(FileExistsError):
        write_report(report, store)
