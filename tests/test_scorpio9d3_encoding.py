"""SCORPIO9D3A: compressed public evidence is bounded and inert."""
from __future__ import annotations

import gzip
import zlib

import pytest

from mio.scorpio9d3_encoding import DecodeError, decode_document

PAGE = b"<html><main>Public documentation from a verified HTTPS page. " + b"A" * 400 + b"</main></html>"


@pytest.mark.parametrize("encoding", ["identity", "gzip", "deflate"])
def test_good_content(encoding):
    compressed = (PAGE if encoding == "identity" else
                  gzip.compress(PAGE) if encoding == "gzip" else zlib.compress(PAGE))
    decoded, actual = decode_document(compressed, encoding, limit=2000)
    assert decoded == PAGE
    assert actual == encoding


def test_case_insensitive_encoding():
    decoded, encoding = decode_document(gzip.compress(PAGE), " GZIP ", limit=2000)
    assert decoded == PAGE and encoding == "gzip"


@pytest.mark.parametrize("encoding", ["br", "gzip, br", "chunked", "x-gzip", "", "identity,gzip"])
def test_unsupported_encodings_denied(encoding):
    with pytest.raises(DecodeError, match="Unsupported"):
        decode_document(PAGE, encoding, limit=2000)


@pytest.mark.parametrize("encoding", ["gzip", "deflate"])
def test_expansion_bomb_denied(encoding):
    bomb = b"R" * 100_000
    data = gzip.compress(bomb) if encoding == "gzip" else zlib.compress(bomb)
    with pytest.raises(DecodeError, match="decoded byte budget"):
        decode_document(data, encoding, limit=2000)


@pytest.mark.parametrize("encoding", ["gzip", "deflate"])
def test_truncated_stream_denied(encoding):
    data = gzip.compress(PAGE) if encoding == "gzip" else zlib.compress(PAGE)
    with pytest.raises(DecodeError, match="Incomplete"):
        decode_document(data[:-3], encoding, limit=2000)


def test_concatenated_gzip_members_denied():
    with pytest.raises(DecodeError, match="multi-member"):
        decode_document(gzip.compress(PAGE) + gzip.compress(PAGE), "gzip", limit=2000)


def test_extra_trailing_junk_denied():
    with pytest.raises(DecodeError, match="multi-member"):
        decode_document(gzip.compress(PAGE) + b"discard me", "gzip", limit=2000)


def test_malformed_deflate_denied():
    with pytest.raises(DecodeError, match="Malformed"):
        decode_document(b"definitely-not-zlib", "deflate", limit=2000)


def test_compressed_byte_budget_denied():
    with pytest.raises(DecodeError, match="compressed byte budget"):
        decode_document(b"X" * 101, "identity", limit=100)


@pytest.mark.parametrize("limit", [-1, 0, 1.5, True, 1_000_001])
def test_invalid_budgets_denied(limit):
    with pytest.raises(DecodeError, match="budget"):
        decode_document(PAGE, "identity", limit=limit)


def test_string_payload_denied():
    with pytest.raises(DecodeError, match="budget"):
        decode_document("not bytes", "identity", limit=2000)


def test_bare_deflate_stream_denied():
    comp = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    raw = comp.compress(PAGE) + comp.flush()
    with pytest.raises(DecodeError, match="Malformed"):
        decode_document(raw, "deflate", limit=2000)
