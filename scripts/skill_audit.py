"""Offline advisory risk scan of a candidate SKILL.md; never execute it.

This heuristic scan is not security approval. Human review of the full skill,
referenced scripts, dependencies and exact pinned source revision is required.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

MAX_SKILL_BYTES = 128 * 1024
PATTERNS = {
    "remote_download_or_install": r"\b(curl|wget|pip\s+install|npm\s+install|npx|git\s+clone)\b",
    "destructive_command": r"\b(rm\s+-rf|mkfs|dd\s+if=|chmod\s+-R|chown\s+-R)\b",
    "credential_access": r"(\.ssh/|\.aws/|api[_ -]?key|private[_ -]?key|password|\.env\b)",
    "unsafe_privilege": r"\b(sudo|su\s+-|--privileged|docker\.sock)\b",
    "untrusted_override": r"(ignore\s+(all\s+)?(previous|system|developer)\s+instructions|disable\s+security)",
    "auto_hooks": r"(pretooluse|posttooluse|settings\.json|hooks\.json)",
}


def scan_markdown(file: Path) -> dict:
    """Produce bounded evidence without executing or granting trust to content."""
    if file.is_symlink() or not file.is_file():
        raise ValueError("Expected a regular non-symlink SKILL.md file")
    if file.name != "SKILL.md":
        raise ValueError("Only SKILL.md is accepted")
    size = file.stat().st_size
    if not 0 < size <= MAX_SKILL_BYTES:
        raise ValueError("Skill file size outside limit")
    raw = file.read_bytes()
    content = raw.decode("utf-8", errors="strict")
    findings = {}
    for name, pattern in PATTERNS.items():
        hits = sorted({m.group(0)[:80] for m in re.finditer(pattern, content, re.IGNORECASE)})
        if hits:
            findings[name] = hits[:5]
    return {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "findings": findings,
        "trusted": False,
        "executable": False,
        "human_review_required": True,
        "note": "Heuristic findings are not definitive; benign docs may trigger warnings.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skill_file", type=Path)
    args = parser.parse_args()
    print(json.dumps(scan_markdown(args.skill_file), indent=2))


if __name__ == "__main__":
    main()
