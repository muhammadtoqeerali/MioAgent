"""Regression tests for missing model.env import and safe local configuration."""

import os

import pytest

from scripts import native_runtime as native
from scripts import ollama_native as ollama


def write_model(tmp_path, text, mode=0o600):
    config = tmp_path / "model.env"
    config.write_text(text, encoding="utf-8")
    os.chmod(config, mode)
    return config


def test_model_env_missing_disables_inference(tmp_path, monkeypatch):
    monkeypatch.setattr(native, "RUNTIME", tmp_path)
    assert native.load_model_config() == {}


def test_model_env_imported_for_local_route(tmp_path, monkeypatch):
    monkeypatch.setattr(native, "RUNTIME", tmp_path)
    write_model(tmp_path, "MIO_LOCAL_MODEL=gpt-oss:20b\nMIO_LOCAL_BASE_URL=http://127.0.0.1:11434/v1\nMIO_MODEL_ROUTE=local\nMIO_ALLOW_CLOUD=false\n")
    assert native.load_model_config() == {
        "MIO_LOCAL_MODEL": "gpt-oss:20b",
        "MIO_LOCAL_BASE_URL": "http://127.0.0.1:11434/v1",
        "MIO_MODEL_ROUTE": "local",
        "MIO_ALLOW_CLOUD": "false",
    }


def test_model_env_rejects_broad_access(tmp_path, monkeypatch):
    monkeypatch.setattr(native, "RUNTIME", tmp_path)
    write_model(tmp_path, "MIO_LOCAL_MODEL=gpt-oss:20b\n", mode=0o644)
    with pytest.raises(RuntimeError, match="accessible to other users"):
        native.load_model_config()


def test_model_env_rejects_symlink(tmp_path, monkeypatch):
    monkeypatch.setattr(native, "RUNTIME", tmp_path)
    other = tmp_path / "other"
    other.write_text("MIO_LOCAL_MODEL=gpt-oss:20b\n")
    (tmp_path / "model.env").symlink_to(other)
    with pytest.raises(OSError):
        native.load_model_config()


@pytest.mark.parametrize("invalid", [
    "MIO_ALLOW_CLOUD=true\n", "MIO_MODEL_ROUTE=cloud\n", "MIO_LOCAL_MODEL=x\nMIO_CLOUD_API_KEY=secret\n",
    "MIO_LOCAL_BASE_URL=http://192.168.1.2:11434/v1\n", "MIO_LOCAL_MODEL=bad model\n",
])
def test_model_env_rejects_unauthorized_settings(tmp_path, monkeypatch, invalid):
    monkeypatch.setattr(native, "RUNTIME", tmp_path)
    write_model(tmp_path, invalid)
    with pytest.raises(RuntimeError):
        native.load_model_config()


def test_ollama_name_validation():
    assert ollama.MODEL_NAME_RE.fullmatch("gpt-oss:20b")
    assert ollama.MODEL_NAME_RE.fullmatch("qwen3:8b")
    assert not ollama.MODEL_NAME_RE.fullmatch("--delete")
    assert not ollama.MODEL_NAME_RE.fullmatch("bad\nvalue")
