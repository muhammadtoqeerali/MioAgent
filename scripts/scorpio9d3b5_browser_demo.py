"""Owner-initiated, one-page public HTTPS fetch and isolated Playwright rendering."""
from __future__ import annotations

import argparse
import json

from mio.scorpio9d3b5_browser import PUBLIC_DEMO_URL, render_approved_demo

APPROVAL = "APPROVE SCORPIO9D3B5 ONE PUBLIC DOCUMENT AND OFFLINE BROWSER TEST"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approval", required=True)
    args = parser.parse_args()
    if args.approval != APPROVAL:
        raise SystemExit("Exact opt-in required for one public HTTPS document fetch")
    result = render_approved_demo(PUBLIC_DEMO_URL, owner_approved=True)
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
