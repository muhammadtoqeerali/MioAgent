"""SCORPIO9C1 isolated tests; never open native production Work SQLite."""
import hashlib
import os
import shutil

import pytest

from mio.scorpio9c_tools import (
    _create_grant,
    _open_input,
    grant,
    input_directory,
    inspect,
    registry,
    revoke,
)
from mio.supervisor_core import approve_plan, create_plan, pause_plan
from mio.work_core import WorkStop, create_project, db


@pytest.fixture
def scope(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    root = private / "work"
    project = create_project(root, "Scoped tools project", "Owner only and offline")
    plan = create_plan(root, project["id"], "Inspect a tiny owner input sample", ["Inspect the exact sample file"])
    approve_plan(root, plan["id"])
    base = private / "tool-inputs"
    base.mkdir(mode=0o700)
    folder = base / project["id"]
    folder.mkdir(mode=0o700)
    (folder / "sample.txt").write_text("private test fixture\n", encoding="utf-8")
    return root, project["id"], plan["id"], folder


def test_registry_is_console_only():
    result = registry()
    assert result["worker_execution"] == "disabled"
    assert result["external_skills"] == "disabled"
    assert result["tools"][0]["network"] is False
    assert result["tools"][0]["execution"] == "owner_console_only"


def test_input_is_strictly_private_and_project_scoped(scope):
    root, project, _plan, folder = scope
    assert input_directory(root, project) == folder
    with pytest.raises((WorkStop, FileNotFoundError)):
        input_directory(root, "f" * 32)
    with pytest.raises(WorkStop):
        _open_input(root, project, "../work/work.db")
    (folder / "link.txt").symlink_to(folder / "sample.txt")
    with pytest.raises(OSError):
        _open_input(root, project, "link.txt")
    (folder / "large.txt").write_bytes(b"x" * (1024 * 1024 + 1))
    with pytest.raises(WorkStop):
        _open_input(root, project, "large.txt")


def test_grant_requires_tty(scope, monkeypatch):
    root, project, plan, _folder = scope
    monkeypatch.setattr(os, "isatty", lambda _fd: False)
    with pytest.raises(WorkStop, match="interactive"):
        grant(root, project, plan, "sample.txt")


def test_grant_is_tied_to_approved_plan(scope):
    root, project, plan, _folder = scope
    with pytest.raises((WorkStop, FileNotFoundError)):
        _create_grant(root, "f" * 32, plan, "sample.txt")
    with pytest.raises(WorkStop):
        _create_grant(root, project, "f" * 32, "sample.txt")
    with pytest.raises(WorkStop):
        _create_grant(root, project, plan, "sample.txt", minutes=60)
    item = _create_grant(root, project, plan, "sample.txt")
    assert item["plan"] == plan and item["project"] == project


def test_exact_inode_not_only_digest(scope):
    root, project, plan, folder = scope
    item = _create_grant(root, project, plan, "sample.txt")
    original = (folder / "sample.txt").read_bytes()
    (folder / "sample.txt").rename(folder / "reserved.txt")
    (folder / "sample.txt").write_bytes(original)
    with pytest.raises(WorkStop, match="identity"):
        inspect(root, item["id"], "sample.txt")


def test_input_mutation_is_denied_without_consuming(scope):
    root, project, plan, folder = scope
    item = _create_grant(root, project, plan, "sample.txt")
    raw = (folder / "sample.txt").read_bytes()
    (folder / "sample.txt").write_bytes(b"X" + raw[1:])
    with pytest.raises(WorkStop, match="content"):
        inspect(root, item["id"], "sample.txt")
    with db(root) as conn:
        assert conn.execute("SELECT used FROM scorpio9c_grants WHERE id=?", (item["id"],)).fetchone()[0] == 0


def test_paused_plan_denied(scope):
    root, project, plan, _folder = scope
    item = _create_grant(root, project, plan, "sample.txt")
    pause_plan(root, plan)
    with pytest.raises(WorkStop, match="active plan"):
        inspect(root, item["id"], "sample.txt")


def test_revoke_is_owner_console_only(scope, monkeypatch):
    root, project, plan, _folder = scope
    item = _create_grant(root, project, plan, "sample.txt")
    monkeypatch.setattr(os, "isatty", lambda _fd: False)
    with pytest.raises(WorkStop):
        revoke(root, item["id"])
    monkeypatch.setattr(os, "isatty", lambda _fd: True)
    revoke(root, item["id"])
    with pytest.raises(WorkStop, match="revoked"):
        inspect(root, item["id"], "sample.txt")


def test_consumed_before_failed_sandbox(scope, monkeypatch):
    from mio import scorpio9c_tools

    root, project, plan, _folder = scope
    item = _create_grant(root, project, plan, "sample.txt")

    def unavailable(_fd):
        raise WorkStop("no sandbox")

    monkeypatch.setattr(scorpio9c_tools, "_sandbox_digest", unavailable)
    with pytest.raises(WorkStop, match="no sandbox"):
        inspect(root, item["id"], "sample.txt")
    with pytest.raises(WorkStop, match="consumed"):
        inspect(root, item["id"], "sample.txt")
    with db(root) as conn:
        phases = [row[0] for row in conn.execute(
            "SELECT kind FROM scorpio9c_events WHERE grant_id=? ORDER BY id", (item["id"],))]
        assert phases == ["issued.local_console", "consumed.before_sandbox"]


def test_exact_single_use_mocked_sandbox(scope, monkeypatch):
    from mio import scorpio9c_tools

    root, project, plan, folder = scope
    item = _create_grant(root, project, plan, "sample.txt")
    monkeypatch.setattr(scorpio9c_tools, "_sandbox_digest", lambda fd: scorpio9c_tools._digest(fd))
    actual = inspect(root, item["id"], "sample.txt")
    assert actual["sha256"] == hashlib.sha256((folder / "sample.txt").read_bytes()).hexdigest()
    with pytest.raises(WorkStop, match="consumed"):
        inspect(root, item["id"], "sample.txt")


def test_real_bubblewrap_required(scope):
    if shutil.which("bwrap") is None:
        pytest.fail("Bubblewrap must exist and operate on release host")
    root, project, plan, folder = scope
    item = _create_grant(root, project, plan, "sample.txt")
    actual = inspect(root, item["id"], "sample.txt")
    assert actual["sha256"] == hashlib.sha256((folder / "sample.txt").read_bytes()).hexdigest()


def test_legacy_bwrap_digest_uses_clean_environment(tmp_path, monkeypatch):
    """The digest tool must pass only its intended FD and sanitized environment."""
    import subprocess

    from mio import scorpio9c_tools as tools

    sample = tmp_path / "sample.txt"
    sample.write_bytes(b"scorpio bounded sandbox regression\n")
    monkeypatch.setattr(tools.shutil, "which", lambda _name: "/usr/bin/bwrap")
    with sample.open("rb") as stream:
        fd = stream.fileno()
        expected = hashlib.sha256(sample.read_bytes()).hexdigest()

        def fake_run(argv, **kwargs):
            assert "--clearenv" not in argv
            assert "--unshare-all" in argv
            assert "--ro-bind-data" in argv
            assert argv[argv.index("--ro-bind-data") + 1:argv.index("--ro-bind-data") + 3] == [str(fd), "/tmp/input"]
            assert kwargs["env"] == {"PATH": "/usr/bin:/bin"}
            assert kwargs["pass_fds"] == (fd,)
            assert kwargs["cwd"] == "/"
            assert kwargs.get("shell", False) is False
            return subprocess.CompletedProcess(argv, 0, (expected + "  /tmp/input\n").encode(), b"")

        monkeypatch.setattr(tools.subprocess, "run", fake_run)
        assert tools._sandbox_digest(fd) == expected
