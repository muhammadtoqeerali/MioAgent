"""SCORPIO9D3B5: offline document-rendering and owner-bound one-page demo."""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from mio import scorpio9d3b5_browser as browser


@pytest.mark.parametrize("url", [
    "https://example.org/", "https://www.python.org/x", "http://www.python.org/",
    "https://127.0.0.1/", "file:///etc/passwd", "https://www.python.org/?x=1",
])
def test_demo_refuses_unapproved_target(url):
    with pytest.raises(browser.BrowserDenied, match="exact public demo URL"):
        browser.render_approved_demo(url, owner_approved=True)


def test_demo_refuses_missing_owner_confirmation():
    with pytest.raises(browser.BrowserDenied, match="owner approval"):
        browser.render_approved_demo(browser.PUBLIC_DEMO_URL)


def test_demo_calls_only_single_public_fetch_and_separate_offline_renderer():
    evidence = {"page_verified": True, "page_sha256": "a" * 64,
                "page_excerpt": "Python public documentation", "page_encoding": "gzip"}
    render = {"verified": True, "rendered_sha256": "b" * 64}
    with (patch.object(browser, "fetch_public_page", return_value=evidence) as fetch,
          patch.object(browser, "render_offline_excerpt", return_value=render) as offline):
        result = browser.render_approved_demo(browser.PUBLIC_DEMO_URL, owner_approved=True)
    fetch.assert_called_once_with(browser.PUBLIC_DEMO_URL)
    offline.assert_called_once_with(evidence["page_excerpt"])
    assert result["page_encoding"] == "gzip"
    assert result["browser_network_enabled"] is False
    assert result["downloads"] is False


def test_demo_refuses_unverified_evidence():
    with (patch.object(browser, "fetch_public_page", return_value={"page_verified": False}),
          pytest.raises(browser.BrowserDenied, match="unverified")):
        browser.render_approved_demo(browser.PUBLIC_DEMO_URL, owner_approved=True)


@pytest.mark.parametrize("bad", ["", " ", "X" * 9000, None, 55])
def test_renderer_rejects_invalid_text_before_browser_start(bad):
    with patch.object(browser, "attest_browser") as attest:
        with pytest.raises(browser.BrowserDenied):
            browser.render_offline_excerpt(bad)
        attest.assert_not_called()


def test_browser_launch_contains_network_unshare_and_disables_downloads():
    assert '--unshare-all' in repr(browser._sandbox.__code__.co_consts)
    assert "accept_downloads=False" in browser._SANDBOX_CODE
    assert "service_workers=\"block\"" in browser._SANDBOX_CODE
    assert 'html.escape(value)' in browser._SANDBOX_CODE
    assert "--disable-background-networking" in browser._SANDBOX_CODE


def test_render_proof_must_match_exact_encoded_excerpt():
    text = "Example <script>document.body.innerHTML = 'evil'</script>"
    valid = {"verified": True,
             "rendered_sha256": hashlib.sha256(text.encode()).hexdigest(),
             "javascript_executed": True, "network": "disabled"}
    candidate = SimpleNamespace(returncode=0, stdout=json.dumps(valid), stderr="")
    with (patch.object(browser, "attest_browser", return_value={"browser_sha256": "a" * 64}),
          patch.object(browser, "_runtime_prefix", return_value=browser.ROOT),
          patch.object(browser, "_sandbox", return_value=["bwrap"]),
          patch.object(browser, "_mount_python", side_effect=lambda c, p: c),
          patch.object(browser.subprocess, "run", return_value=candidate) as runner):
        result = browser.render_offline_excerpt(text)
    assert result["verified"] is True
    argv = runner.call_args.args[0]
    assert "--clearenv" in argv
    assert "--setenv" in argv
    assert "--" in argv
    assert text not in argv


def test_render_proof_refuses_forgery():
    bad = SimpleNamespace(returncode=0, stdout=json.dumps({"verified": True}), stderr="")
    with (patch.object(browser, "attest_browser", return_value={}),
          patch.object(browser, "_runtime_prefix", return_value=browser.ROOT),
          patch.object(browser, "_sandbox", return_value=["bwrap"]),
          patch.object(browser, "_mount_python", side_effect=lambda c, p: c),
          patch.object(browser.subprocess, "run", return_value=bad),
          pytest.raises(browser.BrowserDenied, match="did not match")):
        browser.render_offline_excerpt("hello")
