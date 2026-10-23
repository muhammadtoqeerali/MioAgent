"""No host mutations: isolated checks for vault integrity and agent tool boundaries."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import time
from pathlib import Path

import pytest

from mio import agent_permissions, agent_tools, agent_vault


@pytest.fixture(autouse=True)
def native_mode_scratch(request):
    """Do not misreport POSIX mode-enforcement tests as passing on emulated mounts."""
    if "tmp_path" in request.fixturenames and request.node.name not in (
        "test_ntfs_compatibility_mode_handles_synthetic_file_modes",
    ):
        path = request.getfixturevalue("tmp_path")
        info = path.lstat()
        if info.st_uid != os.getuid() or (stat.S_IMODE(info.st_mode) & 0o022):
            pytest.skip("native-mode fixture cannot be validated on emulated-permission mount")


def private(tmp_path: Path, name: str) -> Path:
    item = tmp_path / name
    item.mkdir(mode=0o700)
    item.chmod(0o700)
    return item


def test_project_boundary_policy_recognizes_but_does_not_harden_root_777():
    from types import SimpleNamespace
    def fake(uid, mode):
        return SimpleNamespace(st_uid=uid, st_mode=stat.S_IFDIR | mode)
    me = os.getuid()
    assert agent_vault.project_boundary_policy(fake(me, 0o755), me) == "owner-controlled"
    if me != 0:
        assert agent_vault.project_boundary_policy(fake(0, 0o777), me) == "root-owned-world-writable-compatibility"
        for owner, mode in ((0, 0o775), (0, 0o755), (me, 0o777)):
            with pytest.raises(agent_vault.VaultError):
                agent_vault.project_boundary_policy(fake(owner, mode), me)
    else:
        with pytest.raises(agent_vault.VaultError):
            agent_vault.project_boundary_policy(fake(999, 0o777), me)


def test_live_vault_rejects_unsafe_root_without_validating_image_content(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_vault, "project_boundary", lambda: "root-owned-world-writable-compatibility")
    with pytest.raises(agent_vault.VaultError, match="cutover blocked"):
        agent_vault.validate_live_image_store()


def test_directory_rejects_unsafe_symlink_and_mode(tmp_path):
    folder = private(tmp_path, "safe")
    agent_vault._directory(folder)
    folder.chmod(0o755)
    with pytest.raises(agent_vault.VaultError):
        agent_vault._directory(folder)
    folder.chmod(0o700)
    shortcut = tmp_path / "shortcut"
    shortcut.symlink_to(folder)
    with pytest.raises(agent_vault.VaultError):
        agent_vault._directory(shortcut)


def test_copy_creates_private_identical_file(tmp_path):
    srcdir = private(tmp_path, "src")
    target = private(tmp_path, "dst")
    src = srcdir / "asset.png"
    src.write_bytes(agent_vault.PNG + b"binary-checksum-test")
    src.chmod(0o600)
    output = target / "asset.png"
    info = agent_vault._copy_verified(src, output, png=True)
    assert info["sha256"] == hashlib.sha256(src.read_bytes()).hexdigest()
    assert output.read_bytes() == src.read_bytes()
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    with pytest.raises(agent_vault.VaultError):
        agent_vault._copy_verified(src, output)


def test_copy_refuses_world_readable_source(tmp_path):
    srcdir = private(tmp_path, "src")
    destdir = private(tmp_path, "dst")
    src = srcdir / "data"
    src.write_bytes(b"private")
    src.chmod(0o644)
    with pytest.raises(agent_vault.VaultError):
        agent_vault._copy_verified(src, destdir / "data")


def test_sqlite_online_backup_is_private_and_consistent(tmp_path):
    directory = private(tmp_path, "db")
    source = directory / "chat.db"
    db = sqlite3.connect(source)
    db.execute("CREATE TABLE messages (message TEXT)")
    db.execute("INSERT INTO messages VALUES ('preserved')")
    db.commit()
    db.close()
    source.chmod(0o600)
    result = directory / "copy.db"
    info = agent_vault._sqlite_backup(source, result)
    assert info["sqlite_quick_check"] == "ok"
    assert stat.S_IMODE(result.stat().st_mode) == 0o600
    with sqlite3.connect(result) as con:
        assert con.execute("SELECT count(*) FROM messages").fetchone()[0] == 1


def test_tool_traversal_and_symlinks_denied(tmp_path):
    folder = private(tmp_path, "repo")
    (folder / "safe.txt").write_text("safe")
    for value in ("../secret", "/etc/passwd", "foo/../safe.txt"):
        with pytest.raises(agent_tools.ToolDenied):
            agent_tools._resolve_safe(folder, value)
    (folder / "alias").symlink_to(folder / "safe.txt")
    with pytest.raises(agent_tools.ToolDenied):
        agent_tools._resolve_safe(folder, "alias")


def test_grant_scopes_expiry_and_capability(tmp_path, monkeypatch):
    root = private(tmp_path, "vault")
    a = root / "agents"
    a.mkdir(mode=0o700)
    g = a / "grants"
    g.mkdir(mode=0o700)
    monkeypatch.setattr(agent_vault, "VAULT", root)
    monkeypatch.setattr(agent_vault, "project_storage_status",
                        lambda: {"live_cutover_supported": True})
    grant_id = "a" * 32
    payload = {"format": 1, "grant": grant_id, "session": "run1", "uid": os.getuid(),
               "capabilities": ["repo.read"], "expires": int(time.time()) + 900}
    target = g / (grant_id + ".json")
    agent_vault._write_new(target, json.dumps(payload).encode())
    assert agent_permissions.require(grant_id, "run1", "repo.read") == payload
    with pytest.raises(agent_permissions.PermissionDenied):
        agent_permissions.require(grant_id, "other", "repo.read")
    with pytest.raises(agent_permissions.PermissionDenied):
        agent_permissions.require(grant_id, "run1", "tests.run")
    with pytest.raises(agent_permissions.PermissionDenied):
        agent_permissions.require("../bad", "run1", "repo.read")
    payload["expires"] = 1
    target.write_text(json.dumps(payload))
    with pytest.raises(agent_permissions.PermissionDenied):
        agent_permissions.require(grant_id, "run1", "repo.read")


def test_workspace_only_new_files_with_grant(tmp_path, monkeypatch):
    root = private(tmp_path, "private")
    a = root / "agents"
    a.mkdir(mode=0o700)
    (a / "workspaces").mkdir(mode=0o700)
    monkeypatch.setattr(agent_vault, "VAULT", root)
    monkeypatch.setattr(agent_permissions, "require", lambda *_: {"ok": True})
    path = agent_tools.write_workspace("x", "jobA", "result.txt", "completed")
    assert path.read_text() == "completed"
    with pytest.raises(agent_tools.ToolDenied):
        agent_tools.write_workspace("x", "jobA", "result.txt", "overwrite")
    with pytest.raises(agent_tools.ToolDenied):
        agent_tools.write_workspace("x", "jobA", "../escape", "unsafe")
    assert not (tmp_path / "escape").exists()


def test_model_cannot_issue_noninteractive_grant(monkeypatch):
    monkeypatch.setattr(agent_permissions.sys.stdin, "isatty", lambda: False)
    with pytest.raises(agent_permissions.PermissionDenied):
        agent_permissions.grant_interactively("jobA", ["repo.read"], 1)


def test_test_command_requires_explicit_suite(monkeypatch):
    monkeypatch.setattr(agent_permissions, "require", lambda *_: {"ok": True})
    for name in ("../tests/test_x.py", "tests/../../etc/passwd", "tests/test_good.py;rm"):
        with pytest.raises(agent_tools.ToolDenied):
            agent_tools.run_approved_tests("x", "jobA", name)


def test_repo_read_does_not_expose_private_vault(tmp_path, monkeypatch):
    repo = private(tmp_path, "repo")
    (repo / ".mioagent-private").mkdir(mode=0o700)
    monkeypatch.setattr(agent_vault, "PROJECT", repo)
    monkeypatch.setattr(agent_permissions, "require", lambda *_: {"ok": True})
    with pytest.raises(agent_tools.ToolDenied):
        agent_tools.read_repo_text("x", "jobA", ".mioagent-private/secret")


def test_portable_checkpoint_does_not_loosen_runtime_paths(tmp_path, monkeypatch):
    """NTFS compatibility applies only beneath the chosen project-local vault."""
    root = tmp_path / "vault"
    root.mkdir(mode=0o700)
    other = tmp_path / "native"
    other.mkdir(mode=0o700)
    root.chmod(0o777)
    other.chmod(0o777)
    monkeypatch.setattr(agent_vault, "VAULT", root)
    monkeypatch.setattr(agent_vault, "compatibility_storage", lambda path: path == root)
    agent_vault._directory(root)
    with pytest.raises(agent_vault.VaultError):
        agent_vault._directory(other)


def test_provisional_vault_refuses_to_issue_persistent_grants(monkeypatch):
    monkeypatch.setattr(agent_vault, "project_storage_status",
                        lambda: {"live_cutover_supported": False})
    with pytest.raises(agent_permissions.PermissionDenied, match="disabled"):
        agent_permissions.require("a" * 32, "run1", "repo.read")


def test_ntfs_compatibility_mode_handles_synthetic_file_modes(tmp_path, monkeypatch):
    """Fallback must not mistake 0777/0666 for an owner-only permission proof."""
    root = tmp_path / "checkout"
    root.mkdir()
    vault = root / ".mioagent-private"
    vault.mkdir(mode=0o700)
    vault.chmod(0o777)
    file = vault / "evidence.txt"
    file.write_text("checkpoint data")
    file.chmod(0o666)
    monkeypatch.setattr(agent_vault, "PROJECT", root)
    monkeypatch.setattr(agent_vault, "VAULT", vault)
    monkeypatch.setattr(agent_vault, "project_boundary", lambda: "root-owned-world-writable-compatibility")
    monkeypatch.setattr(agent_vault, "filesystem_type", lambda path=None: "fuseblk")
    assert agent_vault.compatibility_storage(vault)
    agent_vault._directory(vault)
    assert agent_vault._file(file).st_size == len("checkpoint data")
    link = vault / "link.txt"
    link.symlink_to(file)
    with pytest.raises(agent_vault.VaultError):
        agent_vault._file(link)
    assert agent_vault.project_storage_status()["live_cutover_supported"] is False
    with pytest.raises(agent_vault.VaultError):
        agent_vault.validate_live_image_store()
