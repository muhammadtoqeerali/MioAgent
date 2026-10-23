"""AGENT6E owner inspection client: no tests talk to a live workstation service."""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/mioagent_work_inspect.py"
spec = importlib.util.spec_from_file_location("agent6e_test_client", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
A = "a" * 64
B = "b" * 64
SOURCES = ("mio/work_agent.py", "mio/work_core.py")
D = {SOURCES[0]: A, SOURCES[1]: B}
RID = "1" * 32
PID = "2" * 32
PROMPT = "Review the specified MioAgent source files for maintainability"


def good_run() -> dict:
    return {"id": RID, "mode": "inspection", "state": "needs_review", "prompt": PROMPT,
            "result": "## Read-only source inspection\n**Status:** No code was changed.\n"
                      + "\n".join(f"- `{p}` — SHA-256 `{d}`" for p, d in D.items())
                      + "\n**Not performed:** No patch, tests, or host commands.",
            "events": [{"phase": x} for x in (
                "queued", "inspection.approved", "inspection.scope", "inspection.plan",
                "inspection.read", "inspection.read", "inspection.review")],
            "sources": []}


def test_valid_run_evidence():
    out = mod.evaluate_run(good_run(), SOURCES, D, RID, PROMPT)
    assert out["state"] == "needs_review" and out["files"] == D
    assert not out["tools_granted"] and not out["source_modified"]


@pytest.mark.parametrize("field,value", [
    ("id", "0" * 32), ("prompt", "Other prompt"), ("mode", "engineering"),
    ("state", "answered"), ("state", "queued"), ("state", "failed"),
    ("result", None), ("result", "x" * 8001), ("result", "Not verified"),
])
def test_bad_run_fields_rejected(field, value):
    run = good_run()
    run[field] = value
    with pytest.raises(mod.InspectionError):
        mod.evaluate_run(run, SOURCES, D, RID, PROMPT)


@pytest.mark.parametrize("phase", ["inspection.approved", "inspection.plan", "inspection.read", "inspection.review"])
def test_missing_audit_denied(phase):
    run = good_run()
    run["events"].remove({"phase": phase})
    with pytest.raises(mod.InspectionError, match="audit"):
        mod.evaluate_run(run, SOURCES, D, RID, PROMPT)


def test_missing_file_denied():
    run = good_run()
    run["result"] = run["result"].replace("`mio/work_core.py`", "`redacted`")
    with pytest.raises(mod.InspectionError, match="source evidence"):
        mod.evaluate_run(run, SOURCES, D, RID, PROMPT)


def test_wrong_file_digest_denied():
    run = good_run()
    run["result"] = run["result"].replace("`" + A + "`", "`" + "c" * 64 + "`")
    with pytest.raises(mod.InspectionError, match="Source evidence"):
        mod.evaluate_run(run, SOURCES, D, RID, PROMPT)


def test_duplicate_file_evidence_denied():
    run = good_run()
    run["result"] += "\n`mio/work_core.py`"
    with pytest.raises(mod.InspectionError, match="unique source"):
        mod.evaluate_run(run, SOURCES, D, RID, PROMPT)


def test_fail_close_http_wrong_method():
    with pytest.raises(mod.InspectionError, match="Unapproved"):
        mod.api_json("DELETE", "/api/work/runs/" + RID, "secret")


@pytest.mark.parametrize("path", ["http://evil.test", "/admin", "/api/work/../admin", "/api/work/projects?foo=bar"])
def test_fail_close_wrong_path(path):
    with pytest.raises(mod.InspectionError):
        mod.api_json("GET", path, "secret")


def test_large_api_payload_denied():
    with pytest.raises(mod.InspectionError, match="too large"):
        mod.api_json("POST", "/api/work/projects/" + PID + "/runs", "secret", {"a": "x" * 10000})


def test_successful_http_response(monkeypatch):
    class Resp:
        status = 202
        def read(self, n):
            assert n == mod.MAX_REPLY + 1
            return b'{"id":"' + RID.encode() + b'"}'
        def __enter__(self): return self
        def __exit__(self, *args): return False
    monkeypatch.setattr(mod, "urlopen", lambda req, timeout: Resp())
    assert mod.api_json("GET", "/api/work/runs/" + RID, "fake-token") == {"id": RID}


def test_api_response_limit(monkeypatch):
    class Resp:
        status = 200
        def read(self, n): return b'x' * n
        def __enter__(self): return self
        def __exit__(self, *args): return False
    monkeypatch.setattr(mod, "urlopen", lambda req, timeout: Resp())
    with pytest.raises(mod.InspectionError, match="size"):
        mod.api_json("GET", "/api/work/runs/" + RID, "fake-token")


def test_api_http_unauthorized_no_token_leak(monkeypatch):
    from urllib.error import HTTPError
    def forbidden(req, timeout):
        raise HTTPError(req.full_url, 403, "secret-should-not-appear", {}, None)
    monkeypatch.setattr(mod, "urlopen", forbidden)
    with pytest.raises(mod.InspectionError) as exc:
        mod.api_json("GET", "/api/work/runs/" + RID, "secret-token")
    assert "secret" not in str(exc.value)
    assert "403" in str(exc.value)


def test_receipt_is_new_and_contains_no_prompt(tmp_path, monkeypatch):
    parent = tmp_path / "audit"
    parent.mkdir(mode=0o700)
    monkeypatch.setattr(mod, "RECEIPTS", parent / "agent6e")
    item = mod.save_receipt({"run_id": RID, "files": D})
    assert item.is_file() and item.stat().st_mode & 0o077 == 0
    data = json.loads(item.read_text())
    assert data["phase"] == "AGENT6E_OWNER_INSPECTION"
    assert data["files"] == D
    assert "prompt" not in data
    assert mod.save_receipt({"run_id": RID, "files": D}) != item


def test_receipt_refuses_symlink(tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    parent = tmp_path / "audit"
    parent.mkdir()
    (parent / "agent6e").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(mod, "RECEIPTS", parent / "agent6e")
    with pytest.raises(mod.InspectionError, match="Unsafe"):
        mod.save_receipt({"run_id": RID})
    assert list(outside.iterdir()) == []


def test_read_only_preflight_does_not_post(monkeypatch, capsys):
    monkeypatch.setattr(mod, "git_bytes", lambda *x: b"stable")
    monkeypatch.setattr(mod, "validate_source_list", lambda x: SOURCES)
    monkeypatch.setattr(mod, "preflight_sources", lambda x: D)
    monkeypatch.setattr(mod, "api_json", lambda *args, **kwargs: pytest.fail("No API calls in preflight"))
    assert mod.main(["--mode", "preflight", "--approval", mod.READ_APPROVAL]) == 0
    assert "NO LIVE TASK" in capsys.readouterr().out


def test_no_approval_denies_before_any_activity(monkeypatch):
    monkeypatch.setattr(mod, "git_bytes", lambda *a: pytest.fail("No Git before approval"))
    with pytest.raises(mod.InspectionError, match="authorization"):
        mod.main(["--mode", "submit", "--approval", "wrong", "--project-id", PID])


@pytest.mark.parametrize("bad", ["", "1234", "a" * 33, "z" * 32])
def test_invalid_project_id_denies_before_preflight(monkeypatch, bad):
    monkeypatch.setattr(mod, "validate_source_list", lambda x: SOURCES)
    monkeypatch.setattr(mod, "git_bytes", lambda *args: pytest.fail("No Git"))
    with pytest.raises(mod.InspectionError, match="project ID"):
        mod.main(["--mode", "submit", "--approval", mod.SUBMIT_APPROVAL,
                  "--project-id", bad])


def test_submit_one_approved_task_and_receipt(monkeypatch, capsys):
    monkeypatch.setattr(mod, "git_bytes", lambda *x: b"stable")
    monkeypatch.setattr(mod, "validate_source_list", lambda x: SOURCES)
    monkeypatch.setattr(mod, "preflight_sources", lambda x: D)
    monkeypatch.setattr(mod, "source_digests", lambda x: D)
    monkeypatch.setattr(mod, "save_receipt", lambda record: Path("/project/receipt.json"))
    calls = []
    def api(method, path, token, payload=None):
        calls.append((method, path, payload))
        return {"id": RID, "mode": "inspection_queued"} if method == "POST" else good_run()
    monkeypatch.setattr(mod, "api_json", api)
    fake_native = types.ModuleType("scripts.native_runtime")
    fake_native.get_token = lambda create=False: "test-native-secret"
    fake_scripts = types.ModuleType("scripts")
    fake_scripts.native_runtime = fake_native
    monkeypatch.setitem(sys.modules, "scripts", fake_scripts)
    monkeypatch.setitem(sys.modules, "scripts.native_runtime", fake_native)
    rc = mod.main(["--mode", "submit", "--approval", mod.SUBMIT_APPROVAL,
                   "--project-id", PID])
    assert rc == 0
    assert len(calls) == 2
    assert calls[0][0] == "POST" and calls[1][0] == "GET"
    assert calls[0][2]["approved"] is True
    assert calls[0][2]["sources"] == list(SOURCES)
    assert "test-native-secret" not in capsys.readouterr().out


def test_stale_source_after_task_denied(monkeypatch):
    monkeypatch.setattr(mod, "git_bytes", lambda *x: b"stable")
    monkeypatch.setattr(mod, "validate_source_list", lambda x: SOURCES)
    monkeypatch.setattr(mod, "preflight_sources", lambda x: D)
    monkeypatch.setattr(mod, "source_digests", lambda x: {SOURCES[0]: "c" * 64, SOURCES[1]: B})
    def api(method, path, token, payload=None):
        return {"id": RID, "mode": "inspection_queued"} if method == "POST" else good_run()
    monkeypatch.setattr(mod, "api_json", api)
    monkeypatch.setattr(mod, "save_receipt", lambda x: pytest.fail("No accepted receipt"))
    fake_native = types.ModuleType("scripts.native_runtime")
    fake_native.get_token = lambda create=False: "test-token"
    monkeypatch.setitem(sys.modules, "scripts.native_runtime", fake_native)
    with pytest.raises(mod.InspectionError, match="source changed"):
        mod.main(["--mode", "submit", "--approval", mod.SUBMIT_APPROVAL, "--project-id", PID])


def test_invalid_path_policy_on_real_published_module(tmp_path, monkeypatch):
    # A real local clone in the workstation suite supplies the published policy.
    from mio.agentic_plan_v06b import AgenticPreviewDenied, plan
    with pytest.raises(AgenticPreviewDenied):
        plan(PROMPT, ["../private/secret.txt"])


def test_cli_is_not_a_service_manager():
    content = MODULE_PATH.read_text()
    assert "os.kill(" not in content
    assert "subprocess.Popen(" not in content
    assert "chmod(" not in content
    assert "MIO_AGENT6C_INSPECTION_ENABLED=1" in content
    assert "create=False" in content
