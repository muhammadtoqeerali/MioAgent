#!/usr/bin/env python3
"""Owner-command AGENT6B preview; no Live Work job, grants, shell or source edits."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from mio.agentic_plan_v06b import DEFAULT_SOURCES, AgenticPreviewDenied
from mio.agentic_preview_v06b import execute_owner_preview

PROJECT = Path(__file__).resolve().parents[1]
EXPECTED = Path("/mnt/hdd16T/ToqeerHomeBackup/toqeer/MioAgent")
APPROVAL = "AGENT6B OWNER APPROVES READ ONLY PLAN INSPECT AND AUDIT RECEIPT"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("plan-and-inspect",), required=True)
    parser.add_argument("--approval", required=True)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--source", action="append", default=[])
    args = parser.parse_args()
    if args.approval != APPROVAL or os.geteuid() == 0:
        raise AgenticPreviewDenied("Explicit unprivileged owner preview approval required")
    if PROJECT != EXPECTED or PROJECT.is_symlink() or PROJECT.resolve() != PROJECT:
        raise AgenticPreviewDenied("Unexpected MioAgent checkout path")
    sources = tuple(args.source) if args.source else DEFAULT_SOURCES
    result = execute_owner_preview(PROJECT, args.goal, sources)
    print("=== AGENT6B OWNER PLAN AND READ-ONLY INSPECTION COMPLETE ===")
    print("GOAL TYPE:", result["plan"]["kind"])
    print("PLAN:", " -> ".join(x["id"] for x in result["plan"]["stages"]))
    print("INSPECTED:", len(result["inspection"]), "explicit source files")
    for entry in result["inspection"]:
        print("SOURCE:", entry["path"], "sha256=", entry["sha256"],
              "syntax=", entry["static_syntax"], "definitions=", len(entry["definitions"]))
    print("RESULT: needs_owner_review (no patch, test or execution claims)")
    print("RECEIPT:", result["receipt_path"])
    print("RECEIPT SHA-256:", result["receipt_sha256"])
    print("No shell, network, persistent grant, Work worker change, source edit or Git write.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (AgenticPreviewDenied, OSError, ValueError) as exc:
        print("AGENT6B SAFE STOP:", str(exc)[:250])
        sys.exit(1)
