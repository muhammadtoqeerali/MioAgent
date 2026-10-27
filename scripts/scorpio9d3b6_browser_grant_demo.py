"""Owner-invoked demonstration: one-use public-page grant, then offline rendering.

No model is allowed to issue grants; no unattended Work task is created.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
from pathlib import Path

from mio.scorpio9d3b6_broker import ScopeDenied, execute_granted, issue_one_use

APPROVAL = "APPROVE SCORPIO9D3B6 ONE USE PUBLIC BROWSER EVIDENCE DEMO"
DEMO = "https://www.python.org/"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approval", required=True)
    args = parser.parse_args()
    if args.approval != APPROVAL or os.geteuid() == 0:
        raise SystemExit("Exact owner opt-in required; never run as root")
    parent = Path(f"/var/tmp/mioagent-native-{os.getuid()}")
    project, run = secrets.token_hex(16), secrets.token_hex(16)
    try:
        token = issue_one_use(parent / "scorpio9d3b6-browser-grants", project=project,
                              run=run, url=DEMO, owner_approved=True, ttl=180)
        result = execute_granted(parent / "scorpio9d3b6-browser-grants", project=project,
                                 run=run, url=DEMO, token=token)
        print(json.dumps({"phase": "SCORPIO9D3B6_ONE_USE_BROWSER_GRANT",
                          "live_demo": True, **result}, sort_keys=True))
    except (OSError, ScopeDenied, RuntimeError) as exc:
        raise SystemExit(f"Demo refused or failed: {type(exc).__name__}") from exc


if __name__ == "__main__":
    main()
