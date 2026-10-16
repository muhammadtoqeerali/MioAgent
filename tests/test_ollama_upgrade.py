"""User-installed Ollama binary precedence and ownership tests."""

import stat

import pytest

from scripts import ollama_native as ollama


def test_user_binary_wins_over_system(tmp_path, monkeypatch):
    root = tmp_path / "tools"
    root.mkdir(mode=0o700)
    binary = root / "v0.34.1" / "bin" / "ollama"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o700)
    (root / "current").symlink_to("v0.34.1", target_is_directory=True)
    monkeypatch.setattr(ollama, "USER_INSTALL", root)
    monkeypatch.setattr(ollama.shutil, "which", lambda _: "/usr/local/bin/ollama")
    assert ollama.binary() == str(root / "current" / "bin" / "ollama")


def test_falls_back_when_no_private_install(tmp_path, monkeypatch):
    monkeypatch.setattr(ollama, "USER_INSTALL", tmp_path / "absent")
    monkeypatch.setattr(ollama.shutil, "which", lambda _: "/usr/local/bin/ollama")
    assert ollama.binary() == "/usr/local/bin/ollama"


def test_rejects_insecure_install(tmp_path, monkeypatch):
    root = tmp_path / "tools"
    root.mkdir(mode=0o700)
    root.chmod(0o777)
    monkeypatch.setattr(ollama, "USER_INSTALL", root)
    with pytest.raises(RuntimeError, match="not private"):
        ollama.binary()


def test_rejects_symlink_escape(tmp_path, monkeypatch):
    root = tmp_path / "tools"
    root.mkdir(mode=0o700)
    other = tmp_path / "outside"
    other.mkdir()
    binary = other / "bin" / "ollama"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(stat.S_IRWXU)
    (root / "current").symlink_to(other, target_is_directory=True)
    monkeypatch.setattr(ollama, "USER_INSTALL", root)
    with pytest.raises(RuntimeError, match="escapes private"):
        ollama.binary()
