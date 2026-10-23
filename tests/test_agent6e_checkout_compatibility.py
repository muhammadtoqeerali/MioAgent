"""AGENT6E published-checkout regression: no production tasks, network or writes."""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

CLIENT = Path(__file__).resolve().parents[1] / "scripts/mioagent_work_inspect.py"
spec = importlib.util.spec_from_file_location("agent6e_revision_client", CLIENT)
assert spec and spec.loader
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


def test_published_client_is_new_minimum_and_original_work_pinned():
    assert client.CLIENT_PUBLICATION == "f8712a8692a321e2521615119ed1e26a1b052720"
    assert client.BASELINE == "69319d223fcfcee8983363e588e74292205cc2e4"
    assert len(client.PROTECTED_WORK_SOURCES) == 6
    assert len(set(client.PROTECTED_WORK_SOURCES)) == 6


def test_accepts_descendant_with_unmodified_work_sources(monkeypatch):
    calls = []

    def git(*args):
        calls.append(args)
        if args[0] == "show":
            return args[-1].split(":", 1)[1].encode("utf-8")
        return b""

    monkeypatch.setattr(client, "git_bytes", git)
    client.verify_published_revision()
    assert calls[0] == ("merge-base", "--is-ancestor", client.CLIENT_PUBLICATION, "HEAD")
    assert sum(1 for c in calls if c[0] == "show") == 12


def test_rejects_divergent_or_older_checkout(monkeypatch):
    def git(*args):
        if args[0] == "merge-base":
            raise client.InspectionError("Git source validation unavailable")
        pytest.fail("Protected source inspection must not follow rejected revision")

    monkeypatch.setattr(client, "git_bytes", git)
    with pytest.raises(client.InspectionError):
        client.verify_published_revision()


def test_rejects_changed_live_worker_source(monkeypatch):
    def git(*args):
        if args[0] == "show":
            if args[1] == "HEAD:mio/work_agent.py":
                return b"changed after baseline"
            return b"original accepted bytes"
        return b""

    monkeypatch.setattr(client, "git_bytes", git)
    with pytest.raises(client.InspectionError, match="Work inspection source changed"):
        client.verify_published_revision()


def test_rejects_changed_api_source(monkeypatch):
    def git(*args):
        if args[0] == "show":
            if args[1] == "HEAD:mio/work_api.py":
                return b"patched"
            return b"original"
        return b""

    monkeypatch.setattr(client, "git_bytes", git)
    with pytest.raises(client.InspectionError, match="Work inspection source changed"):
        client.verify_published_revision()


def test_pinned_checkout_is_descendant_using_real_git(tmp_path, monkeypatch):
    """Use an isolated throwaway repository; no MioAgent Git files touched."""
    repo = tmp_path / "git-sandbox"
    repo.mkdir()

    def call(*args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True,
                              capture_output=True, timeout=5)

    call("init", "-q")
    call("config", "user.email", "test@example.invalid")
    call("config", "user.name", "Test")
    (repo / "file.txt").write_text("first\n")
    call("add", "file.txt")
    call("commit", "-qm", "base")
    base = call("rev-parse", "HEAD").stdout.decode().strip()
    (repo / "file.txt").write_text("second\n")
    call("commit", "-qam", "descendant")
    head = call("rev-parse", "HEAD").stdout.decode().strip()
    assert base != head
    monkeypatch.setattr(client, "PROJECT", repo)
    assert client.git_bytes("merge-base", "--is-ancestor", base, "HEAD") == b""
    with pytest.raises(client.InspectionError):
        client.git_bytes("merge-base", "--is-ancestor", head, base)
