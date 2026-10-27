"""SCORPIO9D3B6: approval binding, exactly-once execution and fail-closed audit."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from mio import scorpio9d3b6_broker as broker

P = "a" * 32
R = "b" * 32
U = "https://www.python.org/"
EVIDENCE = {"page_verified": True, "page_excerpt": "Verified Python public website",
            "page_sha256": "3" * 64}
RENDER = {"verified": True, "javascript_executed": True, "network": "disabled",
          "rendered_sha256": "4" * 64}


@pytest.fixture
def store(tmp_path: Path) -> Path:
    parent = tmp_path / "runtime"
    parent.mkdir(mode=0o700)
    return parent / "browser-grants"


def issue(store: Path, **kwargs) -> str:
    return broker.issue_one_use(store, project=P, run=R, url=U,
                                owner_approved=True, **kwargs)


def test_explicit_approval_required(store):
    with pytest.raises(broker.ScopeDenied, match="approval"):
        broker.issue_one_use(store, project=P, run=R, url=U, owner_approved=False)


@pytest.mark.parametrize("url", ["http://example.org/", "https://127.0.0.1/x",
                                  "https://localhost/x", "https://example.org:444/x",
                                  "https://user:pass@example.org/x", "https://example.org/x#frag"])
def test_private_or_unsafe_urls_refused(store, url):
    with pytest.raises(broker.ScopeDenied):
        broker.issue_one_use(store, project=P, run=R, url=url, owner_approved=True)


@pytest.mark.parametrize("project,run", [("a", R), (P, "b"), ("a" * 31 + "G", R)])
def test_invalid_project_run_refused(store, project, run):
    with pytest.raises(broker.ScopeDenied):
        broker.issue_one_use(store, project=project, run=run, url=U, owner_approved=True)


def test_five_minute_limit(store):
    with pytest.raises(broker.ScopeDenied, match="five minutes"):
        issue(store, ttl=301)


def test_one_run_cannot_have_two_grants(store):
    issue(store)
    with pytest.raises(broker.ScopeDenied, match="already"):
        issue(store)


def test_one_use_and_replay_denied(store):
    token = issue(store)
    assert len(token) == 64
    assert broker.claim_once(store, project=P, run=R, url=U, token=token)
    with pytest.raises(broker.ScopeDenied, match="unavailable"):
        broker.claim_once(store, project=P, run=R, url=U, token=token)


def test_expiry_prevents_fetch(store):
    token = issue(store, ttl=2)
    with (patch.object(broker.time, "time", return_value=10**10),
          pytest.raises(broker.ScopeDenied, match="expired")):
        broker.claim_once(store, project=P, run=R, url=U, token=token)


def test_wrong_identity_refused(store):
    token = issue(store)
    with pytest.raises(broker.ScopeDenied):
        broker.claim_once(store, project="c" * 32, run=R, url=U, token=token)
    with pytest.raises(broker.ScopeDenied):
        broker.claim_once(store, project=P, run=R, url="https://www.python.org/a", token=token)
    assert broker.claim_once(store, project=P, run=R, url=U, token=token)


def test_grant_ledger_owner_only_and_no_raw_token(store):
    token = issue(store)
    file = store / "browser-grants.sqlite3"
    assert file.stat().st_mode & 0o777 == 0o600
    assert store.stat().st_mode & 0o777 == 0o700
    assert token.encode() not in file.read_bytes()


def test_success_records_verified_result(store):
    token = broker.issue_one_use(store, project=P, run=R, url=U,
                                 owner_approved=True, ttl=300)
    with (patch.object(broker, "fetch_public_page", return_value=EVIDENCE),
          patch.object(broker, "render_offline_excerpt", return_value=RENDER)):
        result = broker.execute_granted(store, project=P, run=R, url=U, token=token)
    assert result["browser_network"] == "disabled"
    assert result["downloads"] is False and result["installs"] is False
    with sqlite3.connect(store / "browser-grants.sqlite3") as conn:
        assert conn.execute("SELECT state,used FROM grants").fetchone() == ("verified", 1)
    with pytest.raises(broker.ScopeDenied):
        broker.execute_granted(store, project=P, run=R, url=U, token=token)


def test_fetch_failure_still_consumes_grant(store):
    token = broker.issue_one_use(store, project=P, run=R, url=U,
                                 owner_approved=True, ttl=300)
    with (patch.object(broker, "fetch_public_page", side_effect=broker.EvidenceError("no page")),
          pytest.raises(broker.EvidenceError)):
        broker.execute_granted(store, project=P, run=R, url=U, token=token)
    with sqlite3.connect(store / "browser-grants.sqlite3") as conn:
        assert conn.execute("SELECT state,used FROM grants").fetchone() == ("failed", 1)


def test_unverified_browser_proof_refused(store):
    token = broker.issue_one_use(store, project=P, run=R, url=U,
                                 owner_approved=True, ttl=300)
    with (patch.object(broker, "fetch_public_page", return_value=EVIDENCE),
          patch.object(broker, "render_offline_excerpt", return_value={"verified": False}),
          pytest.raises(broker.ScopeDenied, match="proof")):
        broker.execute_granted(store, project=P, run=R, url=U, token=token)


def test_symlink_ledger_refused(store):
    store.mkdir(mode=0o700)
    (store / "browser-grants.sqlite3").symlink_to(store / "other")
    with pytest.raises(broker.ScopeDenied, match="symlink"):
        issue(store)


def test_untrusted_outer_directory_refused(tmp_path):
    parent = tmp_path / "public"
    parent.mkdir(mode=0o777)
    parent.chmod(0o777)
    with pytest.raises(broker.ScopeDenied, match="owner-private"):
        broker.issue_one_use(parent / "grants", project=P, run=R,
                             url=U, owner_approved=True)


def test_no_llm_tool_surface():
    from inspect import getsource

    source = getsource(broker)
    assert "subprocess.run" not in source
    assert "requests.get" not in source
    assert "os.system" not in source
    assert "agent_permissions" not in source
