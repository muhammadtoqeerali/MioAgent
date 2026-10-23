"""AGENT6C dual-opt-in Work inspection queue and source safety contracts."""
from __future__ import annotations

import hashlib
import sys
from types import ModuleType

import pytest

from mio import agentic_work_v06c as worker
from mio.agentic_plan_v06b import AgenticPreviewDenied, plan
from mio.agentic_work_v06c import enabled, execute_inspection_run, format_summary


def fake_details(sources):
    return [{"path": source, "sha256": "a" * 64, "static_syntax": "parsed", "bytes": 40}
            for source in sources]


@pytest.mark.parametrize("flag", ["", "yes", "TRUE", "0", "1 ", "enabled"])
def test_inspection_not_enabled_by_ambiguous_values(monkeypatch, flag):
    monkeypatch.setenv(worker.ENABLED_FLAG, flag)
    assert not enabled()


def test_only_explicit_opt_in_enables(monkeypatch):
    monkeypatch.setenv(worker.ENABLED_FLAG, "1")
    assert enabled()


def test_not_enabled_when_unset(monkeypatch):
    monkeypatch.delenv(worker.ENABLED_FLAG, raising=False)
    assert not enabled()


def test_markdown_report_contains_only_digests_and_no_source_content():
    p = plan("Review Work execution source", ["mio/work_agent.py"])
    text = format_summary(p, fake_details(p.sources))
    assert "mio/work_agent.py" in text and "a" * 64 in text
    assert "No patch, tests, host commands" in text
    assert "needs owner review" in text


@pytest.mark.parametrize("details", [[], [{"path": "mio/other.py", "sha256": "a" * 64, "static_syntax": "parsed", "bytes": 1}],
                                    [{"path": "mio/work_agent.py", "sha256": "notahash", "static_syntax": "parsed", "bytes": 1}],
                                    [{"path": "mio/work_agent.py", "sha256": "a" * 64, "static_syntax": "executed", "bytes": 1}]])
def test_corrupt_evidence_rejected(details):
    p = plan("Review Work execution source", ["mio/work_agent.py"])
    with pytest.raises(AgenticPreviewDenied):
        format_summary(p, details)


@pytest.fixture
def fake_work(monkeypatch, tmp_path):
    """Test the new worker orchestration without creating a live Work database."""
    project = tmp_path / "MioAgent"
    (project / "mio").mkdir(parents=True)
    (project / "mio" / "module.py").write_text("def target():\n    return 7\n", encoding="utf-8")
    monkeypatch.setattr(worker, "PROJECT", project)
    state = {"state": "queued", "mode": "inspection_queued", "prompt": "Inspect this Work module",
             "sources": ["mio/module.py"], "result": None, "error": None, "events": []}
    calls = []
    fake = ModuleType("mio.work_core")
    class WorkStop(ValueError):
        pass
    fake.WorkStop = WorkStop
    def get(_root, _run_id):
        return {**state, "events": list(state["events"])}
    def event(_root, _run_id, phase, detail):
        calls.append(("event", phase))
        state["events"].append({"phase": phase, "detail": detail})
    def update(_root, _run_id, state_name, **kwargs):
        calls.append(("update", state_name))
        state["state"] = state_name
        state.update(kwargs)
    fake.run_info = get
    fake.event = event
    fake.update = update
    monkeypatch.setitem(sys.modules, "mio.work_core", fake)
    import mio
    monkeypatch.setattr(mio, "work_core", fake, raising=False)
    return tmp_path, state, calls


def test_worker_does_not_read_source_before_opt_in(fake_work, monkeypatch):
    root, _state, _calls = fake_work
    monkeypatch.delenv(worker.ENABLED_FLAG, raising=False)
    monkeypatch.setattr(worker, "inspect", lambda *_: pytest.fail("Source should not be read"))
    output = execute_inspection_run(root, "run")
    assert output["state"] == "needs_review"
    assert any(x["phase"] == "inspection.disabled" for x in output["events"])


def test_worker_saves_real_inspection_for_review(fake_work, monkeypatch):
    root, _state, calls = fake_work
    monkeypatch.setenv(worker.ENABLED_FLAG, "1")
    outcome = execute_inspection_run(root, "run")
    assert outcome["state"] == "needs_review"
    assert outcome["mode"] == "inspection"
    assert "mio/module.py" in outcome["result"]
    digest = hashlib.sha256((worker.PROJECT / "mio/module.py").read_bytes()).hexdigest()
    assert digest in outcome["result"]
    assert ("update", "running") in calls
    assert not (worker.PROJECT / ".mioagent-private").exists()


def test_invalid_source_request_fails_without_reading(fake_work, monkeypatch):
    root, state, _calls = fake_work
    state["sources"] = ["../../etc/passwd"]
    monkeypatch.setenv(worker.ENABLED_FLAG, "1")
    monkeypatch.setattr(worker, "inspect", lambda *_: pytest.fail("Must refuse pre-inspection"))
    assert execute_inspection_run(root, "run")["state"] == "failed"


def test_nonqueued_run_is_refused(fake_work, monkeypatch):
    root, state, _calls = fake_work
    state["state"] = "running"
    monkeypatch.setenv(worker.ENABLED_FLAG, "1")
    with pytest.raises(ValueError, match="queued"):
        execute_inspection_run(root, "run")


def test_wrong_mode_is_refused(fake_work, monkeypatch):
    root, state, _calls = fake_work
    state["mode"] = "engineering_queued"
    monkeypatch.setenv(worker.ENABLED_FLAG, "1")
    with pytest.raises(ValueError, match="queued"):
        execute_inspection_run(root, "run")


def test_source_content_is_not_written_to_work_events(fake_work, monkeypatch):
    root, state, _calls = fake_work
    monkeypatch.setenv(worker.ENABLED_FLAG, "1")
    execute_inspection_run(root, "run")
    assert "return 7" not in str(state["events"])


def test_two_distinct_inspections_use_no_source_writes(fake_work, monkeypatch):
    root, _state, _calls = fake_work
    monkeypatch.setenv(worker.ENABLED_FLAG, "1")
    before = (worker.PROJECT / "mio/module.py").read_bytes()
    execute_inspection_run(root, "run")
    assert (worker.PROJECT / "mio/module.py").read_bytes() == before
