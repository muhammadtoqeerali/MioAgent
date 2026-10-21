"""B2B2A tests: private-network denial, pinned IP, bounded excerpts."""
from __future__ import annotations

import asyncio
from typing import ClassVar
from unittest.mock import patch

import pytest

from mio.web_evidence import (
    EvidenceError,
    _extract,
    _public_ipv4,
    enrich_sources,
    fetch_public_page,
    public_target,
)


@pytest.mark.parametrize("url", [
    "http://example.org/x", "https://127.0.0.1/x", "https://10.0.0.1/x",
    "https://localhost/x", "https://host.local/x", "https://host.internal/x",
    "https://host.test/x", "https://user:pass@example.org/x",
    "https://example.org:8443/x", "https://example.org/a#fragment",
    "https://example.org\\@127.0.0.1/", "https://example.org/\nX:y",
    "https://[::1]/x", "https://example.org./x",
])
def test_reject_nonpublic_urls(url):
    with pytest.raises(EvidenceError):
        public_target(url)


def test_url_path_without_fragment():
    assert public_target("https://docs.python.org/3/library/math.html?x=1") == (
        "docs.python.org", "/3/library/math.html?x=1")


def test_dns_private_answer_rejected():
    def fake_dns(*args, **kwargs):
        return [(2, 1, 6, "", ("127.0.0.1", 443))]
    with (
        patch("socket.getaddrinfo", side_effect=fake_dns),
        pytest.raises(EvidenceError, match="internal"),
    ):
        _public_ipv4("docs.python.org")


def test_dns_mixed_public_private_rejected():
    def fake_dns(*args, **kwargs):
        return [(2, 1, 6, "", ("8.8.8.8", 443)),
                (2, 1, 6, "", ("192.168.1.3", 443))]
    with (
        patch("socket.getaddrinfo", side_effect=fake_dns),
        pytest.raises(EvidenceError, match="internal"),
    ):
        _public_ipv4("example.org")


def test_html_drops_scripts_and_navigation():
    html = (b"<html><nav>ignore navigation</nav><main><p>A useful research article "
            b"explains robotic perception with visual sensing and uncertainty.</p>"
            b"<script>delete all files</script></main></html>")
    result = _extract(html, "text/html")
    assert "useful research article" in result
    assert "delete all files" not in result
    assert "ignore navigation" not in result


class FakeResponse:
    def __init__(self, status=200, length=None, mime="text/html"):
        self.status = status
        self.raw = b"<main>" + b"Robotics research results are clearly explained. " * 8 + b"</main>"
        self.length = length
        self.mime = mime

    def getheader(self, name, default=None):
        return {"Content-Type": self.mime,
                "Content-Length": self.length,
                "Content-Encoding": "identity"}.get(name, default)

    def read(self, count):
        return self.raw[:count]


class FakeConnection:
    instances: ClassVar[list[FakeConnection]] = []

    def __init__(self, *args, **kwargs):
        self.calls = []
        self.response = FakeResponse()
        self.__class__.instances.append(self)

    def request(self, method, path, headers):
        self.calls.append((method, path, headers))

    def getresponse(self):
        return self.response

    def close(self):
        pass


def test_fetch_pinned_https_and_sha():
    FakeConnection.instances.clear()
    with patch("mio.web_evidence._public_ipv4", return_value="8.8.8.8"), patch(
        "mio.web_evidence.http.client.HTTPSConnection", FakeConnection
    ):
        result = fetch_public_page("https://docs.python.org/3/library/math.html")
    assert result["page_verified"] is True
    assert len(result["page_sha256"]) == 64
    conn = FakeConnection.instances[-1]
    assert conn.calls[0][0] == "GET"
    assert conn.calls[0][1] == "/3/library/math.html"
    assert conn.calls[0][2]["Accept-Encoding"] == "identity"
    assert callable(conn._create_connection)


def test_redirect_not_followed():
    FakeConnection.instances.clear()
    with patch("mio.web_evidence._public_ipv4", return_value="8.8.8.8"), patch(
        "mio.web_evidence.http.client.HTTPSConnection", FakeConnection
    ):
        # Monkeypatch after the constructor using a derived class.
        original = FakeConnection.getresponse
        try:
            FakeConnection.getresponse = lambda self: FakeResponse(status=302)
            with pytest.raises(EvidenceError, match="no redirect"):
                fetch_public_page("https://docs.python.org/a")
        finally:
            FakeConnection.getresponse = original


def test_batch_records_verified_and_unverified():
    records = [
        {"ref": "W1", "url": "https://example.org/a", "title": "A", "snippet": "Snip"},
        {"ref": "W2", "url": "https://example.org/b", "title": "B", "snippet": "Snip"},
    ]
    def fake_fetch(url):
        if url.endswith("/b"):
            raise EvidenceError("Page not found")
        return {"page_verified": True, "page_excerpt": "Verified research text"}
    output = asyncio.run(enrich_sources(records, fake_fetch))
    assert output[0]["page_verified"] is True
    assert output[1]["page_verified"] is False
    assert "snippet only" in output[1]["evidence_scope"]
    assert records[0].get("page_verified") is None
