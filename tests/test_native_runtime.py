"""Verify the native runtime's non-privileged and credential-safe helpers."""

import os
import stat

import pytest

from scripts import native_runtime as native


def test_token_is_private_and_persistent(tmp_path, monkeypatch):
    monkeypatch.setattr(native, "RUNTIME", tmp_path)
    original = native.get_token(create=True)
    assert len(original) >= 32
    assert native.get_token() == original
    assert stat.S_IMODE((tmp_path / "api-token").stat().st_mode) == 0o600


def test_refuse_insecure_directory(tmp_path):
    path = tmp_path / "unsafe"
    path.mkdir(mode=0o700)
    os.chmod(path, 0o777)
    with pytest.raises(RuntimeError, match="accessible to other users"):
        native.private_dir(path)


def test_refuse_symlink(tmp_path):
    target = tmp_path / "source"
    target.mkdir()
    symlink = tmp_path / "link"
    symlink.symlink_to(target, target_is_directory=True)
    with pytest.raises(RuntimeError, match="Refusing symlink"):
        native.private_dir(symlink)


def test_next_server_renamed_process_recognized(monkeypatch, tmp_path):
    """Next.js may replace its process command with `next-server (v...)`."""
    pid = os.getpid()
    monkeypatch.setattr(native, "DASHBOARD", tmp_path)
    monkeypatch.setattr(native, "command_for_pid", lambda _pid: "next-server (v16.4.1) ")
    original = os.readlink

    def fake_readlink(path):
        if str(path) == f"/proc/{pid}/cwd":
            return str(tmp_path)
        if str(path) == f"/proc/{pid}/exe":
            return "/usr/local/bin/node"
        return original(path)

    monkeypatch.setattr(native.os, "readlink", fake_readlink)
    assert native.is_our_process("dashboard", pid)


def test_next_server_non_node_process_rejected(monkeypatch, tmp_path):
    pid = os.getpid()
    monkeypatch.setattr(native, "DASHBOARD", tmp_path)
    monkeypatch.setattr(native, "command_for_pid", lambda _pid: "next-server (v16.4.1) ")
    original = os.readlink

    def fake_readlink(path):
        if str(path) == f"/proc/{pid}/cwd":
            return str(tmp_path)
        if str(path) == f"/proc/{pid}/exe":
            return "/usr/bin/python3"
        return original(path)

    monkeypatch.setattr(native.os, "readlink", fake_readlink)
    assert not native.is_our_process("dashboard", pid)


def test_other_workdir_next_process_rejected(monkeypatch, tmp_path):
    pid = os.getpid()
    monkeypatch.setattr(native, "DASHBOARD", tmp_path / "not_the_working_directory")
    monkeypatch.setattr(native, "command_for_pid", lambda _pid: "next-server (v16.4.1) ")
    assert not native.is_our_process("dashboard", pid)
