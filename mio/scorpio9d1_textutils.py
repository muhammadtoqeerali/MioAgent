"""SCORPIO9D1: pinned text-utilities contract for owner-approved Work engineering.

The Work coding model supplies untrusted source *data*, never tests, permissions,
commands or filesystem paths. This module uses only platform-authored acceptance
bytes and the already deployed, read-only Bubblewrap verification harness.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from mio.sandbox_verify import HARNESS, PREFLIGHT, _bounded_run, sandbox_argv
from mio.work_core import WorkStop

PREFIX = "SCORPIO9D1 TEXTUTILS: "
MODULE = "textutils.py"
TEST_NAME = "test_textutils_acceptance.py"
TEST_COUNT = 13
MAX_CODE_BYTES = 16_000
MAX_README_BYTES = 8_000

CONTRACT = (
    "\nPINNED SCORPIO9D1 TEXT UTILITIES ACCEPTANCE CONTRACT: "
    "Produce textutils.py implementing four functions using Python standard library only: "
    "normalize_whitespace(text: str) -> str must strip edges and collapse every contiguous "
    "Unicode whitespace run to one ASCII space; count_words(text: str) -> int counts words "
    "after that normalization, zero for empty/whitespace-only input; "
    "is_palindrome(text: str) -> bool compares only Unicode alphanumeric characters "
    "case-insensitively (casefold), with empty/non-alphanumeric text considered a palindrome; "
    "slugify(text: str) -> str must lower-case ASCII letters, retain ASCII digits, "
    "replace runs of other characters with a single hyphen, strip leading/trailing "
    "hyphens, and treat non-ASCII letters as separators. "
    "Only textutils.py and optional README.md are permitted. Do NOT generate test files. "
    "A trusted immutable platform suite independently exercises these functions in a "
    "read-only, network-isolated Bubblewrap process."
)

# Platform-owned test bytes. Never use tests from the model or Work task prompt.
TRUSTED_TEST = '''import unittest
from textutils import count_words, is_palindrome, normalize_whitespace, slugify

class TextUtilitiesAcceptance(unittest.TestCase):
    def test_normalize_spacing(self):
        self.assertEqual(normalize_whitespace("  alpha\\t beta  "), "alpha beta")
    def test_normalize_newlines(self):
        self.assertEqual(normalize_whitespace("a\\n\\r b\\v c"), "a b c")
    def test_normalize_unicode(self):
        self.assertEqual(normalize_whitespace("a\\u2003 b"), "a b")
    def test_normalize_empty(self):
        self.assertEqual(normalize_whitespace("  \\t\\n  "), "")
    def test_count_regular(self):
        self.assertEqual(count_words("  red  blue\\tgreen "), 3)
    def test_count_empty(self):
        self.assertEqual(count_words(" \\u2003 "), 0)
    def test_count_one(self):
        self.assertEqual(count_words("one"), 1)
    def test_palindrome_phrase(self):
        self.assertTrue(is_palindrome("A man, a plan, a canal: Panama!"))
    def test_palindrome_unicode(self):
        self.assertTrue(is_palindrome("ÅbBå"))
    def test_palindrome_empty(self):
        self.assertTrue(is_palindrome("?!  "))
    def test_palindrome_false(self):
        self.assertFalse(is_palindrome("almost palindrome"))
    def test_slug_ascii(self):
        self.assertEqual(slugify("  Hello, WORLD 2026! "), "hello-world-2026")
    def test_slug_unicode_separator(self):
        self.assertEqual(slugify("ab é cd__EF"), "ab-cd-ef")
'''


def is_contract(prompt: str) -> bool:
    """Explicit task marker; implicit topic inference must not enable tests."""
    return isinstance(prompt, str) and prompt.startswith(PREFIX) and len(prompt) > len(PREFIX) + 7


def _review_names(files: dict[str, str]) -> None:
    if (not isinstance(files, dict) or MODULE not in files
            or not set(files).issubset({MODULE, "README.md"})):
        raise WorkStop(
            "Text-utilities engineering requires textutils.py and optional README.md"
        )
    for name, value in files.items():
        if not isinstance(value, str) or not value.strip():
            raise WorkStop("Empty generated text-utilities file refused")
        bound = MAX_CODE_BYTES if name == MODULE else MAX_README_BYTES
        if len(value.encode("utf-8")) > bound:
            raise WorkStop("Generated text-utilities source exceeds file budget")


def _write_private(dest: Path, raw: bytes) -> None:
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def verify(files: dict[str, str], artifact_root: Path) -> dict:
    """Actually execute ONLY inside verified read-only Bwrap, never on host.

    Returns *not passed* on all environment/isolation failures. No shell,
    host package installation, Git operation or model-defined test command.
    """
    _review_names(files)
    try:
        with tempfile.TemporaryDirectory(prefix=".scorpio9d1-", dir=artifact_root) as temp:
            staging = Path(temp)
            os.chmod(staging, 0o700)
            for name, content in files.items():
                _write_private(staging / name, content.encode("utf-8"))
            _write_private(staging / TEST_NAME, TRUSTED_TEST.encode("utf-8"))
            pre_rc, pre_log, pre_timeout, pre_overflow = _bounded_run(
                sandbox_argv(staging, PREFLIGHT), seconds=10,
            )
            if (pre_rc or pre_timeout or pre_overflow
                    or "MIO_SANDBOX_PREFLIGHT_OK" not in pre_log):
                return {"status": "sandbox_unavailable", "passed": False,
                        "tests_run": 0, "reason": "OS isolation preflight refused"}
            rc, output, timed_out, overflow = _bounded_run(
                sandbox_argv(staging, HARNESS), seconds=30,
            )
        counts = re.findall(r"MIO_VERIFIER_TESTS_RUN=(\d+)", output)
        count = int(counts[-1]) if counts else 0
        passed = rc == 0 and not timed_out and not overflow and count == TEST_COUNT
        return {"status": "passed" if passed else "failed", "passed": passed,
                "tests_run": count, "log": output[-3500:],
                "timeout": timed_out, "output_limit": overflow,
                "contract": "SCORPIO9D1.TEXTUTILS.v1"}
    except (OSError, RuntimeError, ValueError) as exc:
        return {"status": "sandbox_unavailable", "passed": False,
                "tests_run": 0, "reason": type(exc).__name__}
