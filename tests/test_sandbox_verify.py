"""Fail-closed sandbox policy and API regression checks without executing untrusted code."""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from mio.api import create_app
from mio.config import Settings
from mio.database import Project, create_database
from mio.project_mode import ProjectPolicyError, apply_draft, validate_draft
from mio.sandbox_verify import (
    SandboxUnavailable,
    sandbox_argv,
    verify_approved_project,
)

SAMPLE = json.dumps({"plan": ["Provide a testable function"], "files": [
    {"path": "hello.py", "content": "def greet():\n    return 'hello'\n"},
    {"path": "test_hello.py", "content": (
        "import unittest\nfrom hello import greet\n"
        "class HelloTest(unittest.TestCase):\n"
        "    def test_greet(self):\n"
        "        self.assertEqual(greet(), 'hello')\n"
    )},
]})
PID = "12345678-1234-1234-1234-123456789012"


def make_workspace(tmp_path, monkeypatch):
    from mio import project_mode as pm

    monkeypatch.setattr(pm, "_mount_type", lambda path: "ext4")
    root = tmp_path / "approved"
    draft = validate_draft(SAMPLE)
    apply_draft(root, PID, draft)
    return root, draft


def test_sandbox_command_no_host_mounts(tmp_path, monkeypatch):
    from mio import sandbox_verify as sv

    monkeypatch.setattr(sv, "sandbox_binary", lambda: ("/usr/bin/bwrap", "/usr/bin/python3"))
    argv = sandbox_argv(tmp_path, "print(123)")
    assert "--unshare-user" in argv
    assert "--unshare-net" in argv
    assert "--unshare-pid" in argv
    assert "--die-with-parent" in argv
    # Legacy Bubblewrap does not support --clearenv.
    # _bounded_run explicitly supplies a sanitized environment.
    assert "--clearenv" not in argv
    assert "--setenv" in argv
    assert "--cap-drop" in argv
    assert "--ro-bind" in argv
    assert "--tmpfs" in argv  # Internal root only, explicitly remounted read-only.
    assert "--size" not in argv
    assert "--remount-ro" in argv
    assert argv.count("--remount-ro") == 3
    assert argv[argv.index("--chdir") - 2:argv.index("--chdir")] == ["--remount-ro", "/"]
    assert "--" in argv
    assert "--bind" not in argv
    assert "/home" not in argv and "/mnt" not in argv
    assert "/var/tmp" not in argv
    assert argv[-5:] == ["/usr/bin/python3", "-I", "-B", "-c", "print(123)"]


def test_system_python_resolves_update_alternatives_before_sandbox(monkeypatch):
    """Do not require /etc/alternatives to exist inside the sandbox."""
    from pathlib import Path

    from mio import sandbox_verify as sv

    # /usr/bin/true stands in for the system bubblewrap binary in this test;
    # no sandbox process is launched. This checks the trusted path handling.
    monkeypatch.setattr(sv, "TRUSTED_BWRAP", Path("/usr/bin/true"))
    monkeypatch.setattr(sv, "TRUSTED_PYTHON", Path("/usr/bin/python3"))
    tool, python = sv.sandbox_binary()
    assert tool == str(Path("/usr/bin/true").resolve(strict=True))
    assert python == str(Path("/usr/bin/python3").resolve(strict=True))
    assert python.startswith("/usr/")
    assert Path(python).is_file()
    argv = sv.sandbox_argv(Path("/tmp"), "print('ok')")
    assert argv[-5] == python
    assert "--ro-bind" in argv
    assert "/etc" not in argv


def test_rejects_untrusted_system_python(tmp_path, monkeypatch):
    from mio import sandbox_verify as sv

    monkeypatch.setattr(sv, "TRUSTED_BWRAP", tmp_path / "bwrap-missing")
    with pytest.raises(SandboxUnavailable, match="unavailable"):
        sv.sandbox_binary()


def test_approved_artifact_only_and_result(tmp_path, monkeypatch):
    from mio import sandbox_verify as sv

    root, draft = make_workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(sv, "preflight", lambda p: {"preflight": "passed"})
    monkeypatch.setattr(sv, "sandbox_argv", lambda p, code: ["fake", code])
    def fake_run(argv, *, seconds=30):
        assert "unittest" in argv[-1]
        return 0, "Ran 1 test - OK\nMIO_VERIFIER_TESTS_RUN=1\n", False, False
    monkeypatch.setattr(sv, "_bounded_run", fake_run)
    result = verify_approved_project(root, PID, draft)
    assert result["passed"] and result["tests_run"] == 1
    assert not list(root.glob(".mio-sandbox-*"))
    assert (root / PID / "hello.py").read_text().startswith("def greet")


def test_failed_tests_not_reported_as_success(tmp_path, monkeypatch):
    from mio import sandbox_verify as sv

    root, draft = make_workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(sv, "preflight", lambda p: {})
    monkeypatch.setattr(sv, "sandbox_argv", lambda p, code: ["fake"])
    monkeypatch.setattr(sv, "_bounded_run", lambda argv, *, seconds=30: (
        1, "FAILED\nMIO_VERIFIER_TESTS_RUN=2\n", False, False,
    ))
    result = verify_approved_project(root, PID, draft)
    assert not result["passed"] and result["outcome"] == "failed"
    assert result["tests_run"] == 2


def test_tampered_approved_files_cannot_execute(tmp_path, monkeypatch):
    from mio import sandbox_verify as sv

    root, draft = make_workspace(tmp_path, monkeypatch)
    (root / PID / "hello.py").write_text("tampered", encoding="utf-8")
    monkeypatch.setattr(sv, "preflight", lambda p: pytest.fail("Must not execute preflight"))
    with pytest.raises(ProjectPolicyError, match="differ"):
        verify_approved_project(root, PID, draft)


def test_no_test_files_skip_execution(tmp_path, monkeypatch):
    from mio import sandbox_verify as sv

    root = tmp_path / "projects"
    from mio import project_mode as pm
    monkeypatch.setattr(pm, "_mount_type", lambda p: "ext4")
    draft = validate_draft(json.dumps({"plan": ["Write"], "files": [
        {"path": "hello.py", "content": "print('hello')\n"},
    ]}))
    apply_draft(root, PID, draft)
    monkeypatch.setattr(sv, "preflight", lambda p: pytest.fail("No tests: no execution"))
    assert verify_approved_project(root, PID, draft)["outcome"] == "no_tests"


def test_api_verification_requires_feature_and_approval(tmp_path, monkeypatch):
    from mio import project_mode as pm
    monkeypatch.setattr(pm, "_mount_type", lambda p: "ext4")
    root = tmp_path / "artifacts"
    draft = validate_draft(SAMPLE)
    apply_draft(root, PID, draft)
    settings = Settings(
        mio_api_token="X" * 48,
        mio_database_url=f"sqlite+pysqlite:///{tmp_path / 'database.db'}",
        mio_workspace_root=tmp_path,
        mio_project_root=root,
        mio_enable_project_mode=True,
        mio_enable_sandbox_verify=False,
    )
    engine, sessions = create_database(settings.mio_database_url)
    with sessions.begin() as db:
        db.add(Project(id=PID, title="Approved", requirements="Build something testable",
                       status="completed", workspace_path=str(root / PID),
                       draft_json=json.dumps(draft)))
    engine.dispose()
    headers = {"Authorization": f"Bearer {settings.mio_api_token}"}
    with TestClient(create_app(settings)) as client:
        assert client.post(f"/api/projects/{PID}/verify", headers=headers,
                           json={"approved": True}).status_code == 409
        assert client.get(f"/api/projects/{PID}/verification", headers=headers).json()[
            "status"] == "not_run"
        anonymous = client.post(f"/api/projects/{PID}/verify", json={"approved": True})
        assert anonymous.status_code == 401


def test_api_verification_records_result_async(tmp_path, monkeypatch):
    from mio import project_mode as pm
    from mio import project_verification_tasks as pvt

    monkeypatch.setattr(pm, "_mount_type", lambda p: "ext4")
    root = tmp_path / "artifacts"
    draft = validate_draft(SAMPLE)
    apply_draft(root, PID, draft)
    settings = Settings(
        mio_api_token="Q" * 48,
        mio_database_url=f"sqlite+pysqlite:///{tmp_path / 'running.db'}",
        mio_workspace_root=tmp_path,
        mio_project_root=root,
        mio_enable_project_mode=True,
        mio_enable_sandbox_verify=True,
        mio_poll_seconds=0.1,
    )
    engine, sessions = create_database(settings.mio_database_url)
    with sessions.begin() as db:
        db.add(Project(id=PID, title="Approved", requirements="Build something testable",
                       status="completed", workspace_path=str(root / PID),
                       draft_json=json.dumps(draft)))
    engine.dispose()
    monkeypatch.setattr(pvt, "verify_approved_project", lambda *a: {
        "outcome": "passed", "passed": True, "tests_run": 1,
        "log": "mock test", "executed": True,
    })
    headers = {"Authorization": f"Bearer {settings.mio_api_token}"}
    with TestClient(create_app(settings)) as client:
        assert client.post(f"/api/projects/{PID}/verify", headers=headers,
                           json={"approved": False}).status_code == 422
        queued = client.post(f"/api/projects/{PID}/verify", headers=headers,
                             json={"approved": True})
        assert queued.status_code == 202, queued.text
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = client.get(f"/api/projects/{PID}/verification", headers=headers).json()
            if result["status"] == "completed":
                break
            time.sleep(0.05)
        assert result["status"] == "completed", result
        assert result["result"]["passed"] is True
        assert client.get(f"/api/projects/{PID}", headers=headers).json()["status"] == "completed"


def test_sandbox_launcher_scrubs_inherited_environment(monkeypatch):
    """Verify environment scrubbing without relying on Bubblewrap version."""
    import sys

    from mio import sandbox_verify as sv

    sentinel = "SCORPIO_TEST_HOST_SECRET_SENTINEL"
    monkeypatch.setenv(sentinel, "must-not-reach-child")

    code = (
        "import os; "
        "assert 'SCORPIO_TEST_HOST_SECRET_SENTINEL' not in os.environ; "
        "assert os.environ.get('PATH') == '/usr/bin:/bin'; "
        "print('SCORPIO_ENV_SCRUB_OK')"
    )

    rc, log, timed, overflow = sv._bounded_run(
        [sys.executable, "-I", "-B", "-c", code],
        seconds=10,
    )

    assert (rc, timed, overflow) == (0, False, False), log
    assert "SCORPIO_ENV_SCRUB_OK" in log
