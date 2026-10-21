"""B2B2A: bounded public-HTTPS page evidence for MioAgent Work research.

Search snippets are *not* full-page evidence. Never execute webpage instructions.
DNS is resolved once and the approved public IP is pinned for the TLS connection,
preventing a second resolver lookup from changing to an internal address.
"""
from __future__ import annotations

import asyncio
import hashlib
import http.client
import ipaddress
import re
import socket
import ssl
from collections.abc import Callable
from html.parser import HTMLParser
from urllib.parse import urlsplit

MAX_RESPONSE = 420_000
MAX_EXCERPT = 4000
MAX_URL = 1500
MAX_PAGES = 3
TIMEOUT = 7.0


class EvidenceError(ValueError):
    """Reject unsafe or unavailable page without exposing an internal service."""


class _PageText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.excluded = 0
        self.count = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in {"script", "style", "noscript", "nav", "footer", "header", "svg", "form"}:
            self.excluded += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "nav", "footer", "header", "svg", "form"}:
            self.excluded = max(0, self.excluded - 1)

    def handle_data(self, data: str) -> None:
        if not self.excluded and self.count < MAX_EXCERPT * 4:
            self.parts.append(data)
            self.count += len(data)


def public_target(url: str) -> tuple[str, str]:
    """Return DNS name and origin-relative path; never admit internal/literal targets."""
    if not isinstance(url, str) or not 12 <= len(url) <= MAX_URL:
        raise EvidenceError("Invalid page URL length")
    if any(ord(c) < 32 for c in url) or "\\" in url:
        raise EvidenceError("Malformed URL")
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise EvidenceError("Malformed URL") from exc
    if (parsed.scheme != "https" or not hostname or port not in (None, 443)
            or parsed.username or parsed.password or parsed.fragment):
        raise EvidenceError("Only public HTTPS URLs on port 443 are permitted")
    host = hostname.lower().rstrip(".")
    if host != hostname.lower() or not host.isascii():
        raise EvidenceError("Invalid hostname")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise EvidenceError("IP-literal URL blocked")
    if (len(host) > 253 or "." not in host
            or host.endswith((".local", ".internal", ".localhost", ".test", ".invalid"))
            or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                   for label in host.split("."))):
        raise EvidenceError("Non-public hostname")
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return host, path


def _public_ipv4(host: str) -> str:
    """Reject all non-global resolver answers; support IPv4 for audited pinning."""
    try:
        answers = socket.getaddrinfo(host, 443, family=socket.AF_INET,
                                     type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise EvidenceError("Public DNS lookup failed") from exc
    addresses = {item[4][0] for item in answers}
    if not addresses:
        raise EvidenceError("No IPv4 address available")
    if not all(ipaddress.ip_address(addr).is_global for addr in addresses):
        raise EvidenceError("DNS returned an internal or reserved address")
    return min(addresses)


def _extract(content: bytes, content_type: str) -> str:
    value = content.decode("utf-8", errors="replace")
    if content_type in {"text/html", "application/xhtml+xml"}:
        parser = _PageText()
        parser.feed(value)
        value = " ".join(parser.parts)
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) < 60:
        raise EvidenceError("Page lacks usable readable text")
    return value[:MAX_EXCERPT]


def fetch_public_page(url: str) -> dict:
    """Retrieve at most 420 KB, without cookies, redirects, proxies or credentials.

    DNS-approved IP is pinned to the TLS socket; certificate/SNI still use host.
    Untrusted HTML remains inert text. Only HTTP 200 HTML/plaintext is accepted.
    """
    host, path = public_target(url)
    ip = _public_ipv4(host)
    connection = http.client.HTTPSConnection(host, port=443, timeout=TIMEOUT,
                                             context=ssl.create_default_context())

    def pinned_connect(address, timeout=None, source_address=None):
        return socket.create_connection((ip, 443), timeout=timeout,
                                        source_address=source_address)

    connection._create_connection = pinned_connect
    try:
        connection.request("GET", path, headers={
            "Host": host, "User-Agent": "MioAgent-Research/0.5",
            "Accept": "text/html,application/xhtml+xml,text/plain",
            "Accept-Encoding": "identity", "Connection": "close",
        })
        response = connection.getresponse()
        if response.status != 200:
            raise EvidenceError(f"Page returned HTTP {response.status}; no redirect followed")
        media_type = response.getheader("Content-Type", "").split(";", 1)[0].lower().strip()
        if media_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
            raise EvidenceError("Page media type is not supported")
        if response.getheader("Content-Encoding", "identity").lower() != "identity":
            raise EvidenceError("Compressed page not supported")
        length = response.getheader("Content-Length")
        if length and (not length.isdigit() or int(length) > MAX_RESPONSE):
            raise EvidenceError("Page exceeds byte budget")
        raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise EvidenceError("Page exceeded byte budget")
        excerpt = _extract(raw, media_type)
        return {"page_verified": True, "page_excerpt": excerpt,
                "page_sha256": hashlib.sha256(raw).hexdigest(),
                "evidence_scope": "public page excerpt, not full publication verification"}
    except (OSError, ssl.SSLError, http.client.HTTPException, TimeoutError) as exc:
        raise EvidenceError("Page transport unavailable") from exc
    finally:
        connection.close()


async def enrich_sources(sources: list[dict], fetcher: Callable = fetch_public_page) -> list[dict]:
    """Keep search provenance and attach verified page excerpts where possible.

    At most three pages are fetched; failures are explicit and never upgraded to
    verified evidence. This function does not crawl or fetch discovered links.
    """
    records = [dict(item) for item in sources[:6]]
    for item in records:
        item["page_verified"] = False
    for item in records[:MAX_PAGES]:
        url = item.get("url")
        try:
            details = await asyncio.to_thread(fetcher, url)
            if not details.get("page_verified") or not details.get("page_excerpt"):
                raise EvidenceError("Page has no verified excerpt")
            item.update(details)
        except (EvidenceError, OSError, TypeError, ValueError):
            item["evidence_scope"] = "search snippet only; page not verified"
    return records
