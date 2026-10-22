"""Review AUT4A/AUT4B code evidence before separate manual approval to apply.

Usage: python -m scripts.autonomy_reviews preview CAMPAIGN [--show-diffs]
       python -m scripts.autonomy_reviews seal CAMPAIGN --owner-acknowledge
       python -m scripts.autonomy_reviews verify CAMPAIGN [--show-diffs]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mio.autonomy_reviews import (
    build_dossier,
    review_overview,
    seal_review,
    verify_seal,
)
from scripts.native_runtime import RUNTIME


def run(argv: list[str] | None = None, *, store: Path | None = None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("preview", "seal", "verify"):
        cmd = sub.add_parser(action)
        cmd.add_argument("campaign", help="Existing 32-character AUT4A campaign ID")
        if action == "seal":
            cmd.add_argument("--owner-acknowledge", action="store_true")
        else:
            cmd.add_argument("--show-diffs", action="store_true")
    args = parser.parse_args(argv)
    location = RUNTIME / "autonomy" if store is None else store
    if args.action == "preview":
        return review_overview(build_dossier(location, args.campaign), show_diffs=args.show_diffs)
    if args.action == "seal":
        return seal_review(location, args.campaign, owner_acknowledged=args.owner_acknowledge)
    return verify_seal(location, args.campaign, show_diffs=args.show_diffs)


def main() -> None:
    try:
        print(json.dumps(run(), indent=2, sort_keys=True))
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        raise SystemExit(f"STOP: {type(exc).__name__}: {str(exc)[:240]}") from exc


if __name__ == "__main__":
    main()
