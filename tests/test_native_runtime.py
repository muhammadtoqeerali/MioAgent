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
