"""AUT1 backlog persistence, schema, gates and bounded untrusted model plans."""

from __future__ import annotations

import json
import os
import stat

import pytest

from mio.autonomy_program import (
    PHASES,
    initial_program,
    initialize,
    parse_proposal,
    read_program,
    ready_tasks,
    save_proposal,
)

BASE = "0a6def4efb03279204999a2940c43a8f7183a62c"


def _store(tmp_path):
    parent = tmp_path / "runtime"
    parent.mkdir(mode=0o700)
    os.chmod(parent, 0o700)
    return parent / "autonomy"


def test_roadmap_is_bounded_and_dependencies_exist():
    data = initial_program(BASE)
    assert data["scope"] == "planning_only_no_automatic_execution"
    assert len(data["tasks"]) == len(PHASES)
    ids = {t["id"] for t in data["tasks"]}
    assert {d for t in data["tasks"] for d in t["depends_on"]} <= ids
    assert {t["id"] for t in ready_tasks(data)} == {"ui-live", "model-eval"}
    assert not any(t["verified_by_owner"] for t in data["tasks"])


def test_invalid_commit_rejected():
    with pytest.raises(ValueError):
        initial_program("main")


def test_program_private_and_idempotent(tmp_path):
    store = _store(tmp_path)
    data, created = initialize(store, BASE)
    assert created
    assert not initialize(store, BASE)[1]
    assert read_program(store) == data
    assert stat.S_IMODE((store / "program.json").stat().st_mode) == 0o600
    assert stat.S_IMODE(store.stat().st_mode) == 0o700
    with pytest.raises(RuntimeError):
        initialize(store, "e" * 40)


def test_symlink_state_refused(tmp_path):
    store = _store(tmp_path)
    initialize(store, BASE)
    original = store / "program.json"
    original.rename(store / "keep.json")
    original.symlink_to(store / "keep.json")
    with pytest.raises(RuntimeError):
        read_program(store)


def test_store_refuses_untrusted_dependencies(tmp_path):
    store = _store(tmp_path)
    initialize(store, BASE)
    record = json.loads((store / "program.json").read_text())
    record["tasks"][0]["depends_on"] = ["unknown"]
    (store / "program.json").write_text(json.dumps(record))
    with pytest.raises(RuntimeError):
        read_program(store)


@pytest.mark.parametrize("value", [
    "not json", "{}", '{"steps": []}', '{"steps": ["ok", "ok", "ok"]}',
    '{"steps": ["Valid step one", "Valid step two", "Valid step three"], "shell": true}',
])
def test_invalid_model_plan_refused(value):
    with pytest.raises(ValueError):
        parse_proposal(value)


def test_stores_proposal_as_untrusted_and_blocks_repeated_proposals(tmp_path):
    store = _store(tmp_path)
    initialize(store, BASE)
    steps = ["Inspect dependencies and baseline tests", "Propose bounded changes for owner review",
             "Specify independent acceptance test and rollback"]
    saved = save_proposal(store, "ui-live", steps, "gpt-oss:20b")
    assert saved["state"] == "awaiting_review"
    assert saved["proposal"]["status"] == "untrusted_model_proposal"
    assert len(saved["proposal"]["sha256"]) == 64
    assert "ui-live" not in {t["id"] for t in ready_tasks(read_program(store))}
    with pytest.raises(RuntimeError):
        save_proposal(store, "ui-live", steps, "gpt-oss:20b")
    with pytest.raises(RuntimeError):
        save_proposal(store, "shared-web", steps, "gpt-oss:20b")


def test_no_owner_verification_can_be_written_via_proposal(tmp_path):
    store = _store(tmp_path)
    initialize(store, BASE)
    save_proposal(store, "model-eval", ["Inspect available models safely",
                                       "Run bounded local evaluation probes",
                                       "Report scores without promoting any model"], "qwen3.5:9b")
    assert not any(x["verified_by_owner"] for x in read_program(store)["tasks"])
