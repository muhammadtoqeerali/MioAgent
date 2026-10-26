"""SCORPIO9D3A: protected public HTTPS connection and encoding integration."""
from __future__ import annotations

import gzip
import hashlib
import zlib
from unittest.mock import patch

import pytest

from mio.web_evidence import EvidenceError, fetch_public_page

DOC = b"<html><main>Verified public software documentation explains the standard Python language. " + b"A" * 120 + b"</main></html>"


def fake_https(payload: bytes, encoding: str, *, status: int = 200, kind: str = "text/html"):
    class Response:
        def __init__(self):
            self.status = status

        def getheader(self, name, default=None):
            return {"Content-Type": kind, "Content-Encoding": encoding,
                    "Content-Length": str(len(payload))}.get(name, default)

        def read(self, count):
            return payload[:count]

    class Connection:
        last = None

        def __init__(self, *args, **kwargs):
            self.__class__.last = self
            self.request_headers = None

        def request(self, method, path, headers):
            assert method == "GET" and path == "/3/library/"
            self.request_headers = headers

        def getresponse(self):
            return Response()

        def close(self):
            pass

    return Connection


@pytest.mark.parametrize("encoding", ["identity", "gzip", "deflate"])
def test_real_client_accepts_bounded_supported_encoding(encoding):
    payload = DOC if encoding == "identity" else (gzip.compress(DOC) if encoding == "gzip" else zlib.compress(DOC))
    conn = fake_https(payload, encoding)
    with (patch("mio.web_evidence._public_ipv4", return_value="8.8.8.8"),
          patch("mio.web_evidence.http.client.HTTPSConnection", conn)):
        result = fetch_public_page("https://docs.python.org/3/library/")
    assert result["page_verified"] is True
    assert result["page_sha256"] == hashlib.sha256(payload).hexdigest()
    assert result["page_decoded_sha256"] == hashlib.sha256(DOC).hexdigest()
    assert result["page_encoding"] == encoding
    assert "Verified public software documentation" in result["page_excerpt"]
    assert conn.last.request_headers["Accept-Encoding"] == "identity"
    assert callable(conn.last._create_connection)


def test_compression_bomb_never_reaches_parser():
    bomb = gzip.compress(b"X" * 600_000)
    conn = fake_https(bomb, "gzip")
    with (patch("mio.web_evidence._public_ipv4", return_value="8.8.8.8"),
          patch("mio.web_evidence.http.client.HTTPSConnection", conn),
          patch("mio.web_evidence._extract", side_effect=AssertionError("must not parse")),
          pytest.raises(EvidenceError, match="decoded byte budget")):
        fetch_public_page("https://docs.python.org/3/library/")


def test_brotli_cannot_bypass_rejection():
    conn = fake_https(b"anything", "br")
    with (patch("mio.web_evidence._public_ipv4", return_value="8.8.8.8"),
          patch("mio.web_evidence.http.client.HTTPSConnection", conn),
          pytest.raises(EvidenceError, match="Unsupported public page compression")):
        fetch_public_page("https://docs.python.org/3/library/")


def test_redirect_remains_denied():
    conn = fake_https(gzip.compress(DOC), "gzip", status=302)
    with (patch("mio.web_evidence._public_ipv4", return_value="8.8.8.8"),
          patch("mio.web_evidence.http.client.HTTPSConnection", conn),
          pytest.raises(EvidenceError, match="no redirect")):
        fetch_public_page("https://docs.python.org/3/library/")
