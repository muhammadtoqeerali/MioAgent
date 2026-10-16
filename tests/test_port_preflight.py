"""Listen-state detection must not mistake TIME_WAIT for an active service."""

import socket
import subprocess

import pytest

from scripts import native_runtime as native


def test_port_listeners_rejects_invalid_port():
    for value in (0, -1, 65536):
        with pytest.raises(ValueError, match="Invalid TCP port"):
            native.port_listeners(value)


def test_port_available_no_listener(monkeypatch):
    def fake_run(command, **kwargs):
        assert command[:4] == ["ss", "-H", "-ltnp", "sport = :3000"]
        assert kwargs["check"] is True
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(native.subprocess, "run", fake_run)
    assert native.port_available(3000) is True


def test_port_unavailable_with_actual_listener(monkeypatch):
    fake_row = 'LISTEN 0 511 127.0.0.1:3000 0.0.0.0:* users:(("next-server",pid=42,fd=1))\n'

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout=fake_row, stderr="")

    monkeypatch.setattr(native.subprocess, "run", fake_run)
    assert native.port_available(3000) is False
    assert "next-server" in native.port_listeners(3000)


def test_port_queries_do_not_bind_or_kill(monkeypatch):
    def fake_run(command, **kwargs):
        assert command[0] == "ss"
        assert "-ltnp" in command
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(native.subprocess, "run", fake_run)
    assert native.port_listeners(3000) == ""


def test_real_tcp_listener_detection():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        port = server.getsockname()[1]
        server.listen(1)
        assert native.port_available(port) is False
    assert native.port_available(port) is True
