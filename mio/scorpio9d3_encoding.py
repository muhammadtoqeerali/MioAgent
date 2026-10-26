"""Bounded public HTTPS payload decoding; never a download or execution tool.

The web evidence client retains the original HTTPS, DNS, content-type, redirect,
compressed-byte and excerpt gates. Compression does not change those permissions.
"""

from __future__ import annotations

import zlib

ALLOWED = frozenset({"identity", "gzip", "deflate"})


class DecodeError(ValueError):
    """Unsafe, malformed, unsupported or oversized page representation."""


def decode_document(payload: bytes, content_encoding: str, *, limit: int) -> tuple[bytes, str]:
    """Return an at-most-limit decoded representation and a normalized encoding.

    Refuse nested codings, concatenated gzip streams, incomplete members,
    excess output, malformed zlib streams, and unsupported encodings.  Bounds
    are applied by the decompressor before emitting excessive output.
    """
    if not isinstance(payload, bytes) or type(limit) is not int or not 1 <= limit <= 1_000_000:
        raise DecodeError("Invalid document decoding budget")
    if not isinstance(content_encoding, str):
        raise DecodeError("Invalid document content encoding")
    encoding = content_encoding.strip().lower()
    if encoding not in ALLOWED:
        raise DecodeError("Unsupported public page compression")
    if len(payload) > limit:
        raise DecodeError("Page exceeded compressed byte budget")
    if encoding == "identity":
        return payload, encoding
    wbits = zlib.MAX_WBITS + 16 if encoding == "gzip" else zlib.MAX_WBITS
    try:
        decompressor = zlib.decompressobj(wbits)
        decoded = decompressor.decompress(payload, limit + 1)
    except zlib.error as exc:
        raise DecodeError("Malformed compressed page") from exc
    if len(decoded) > limit:
        raise DecodeError("Page exceeded decoded byte budget")
    if not decompressor.eof or decompressor.unused_data or decompressor.unconsumed_tail:
        raise DecodeError("Incomplete or multi-member compressed page")
    return decoded, encoding
