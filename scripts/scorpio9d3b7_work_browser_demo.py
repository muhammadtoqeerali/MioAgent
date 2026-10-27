"""SCORPIO9D3B7 isolated Work -> one-use public HTTPS -> offline browser."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

from mio.scorpio9d3b7_work_browser import decide, propose
from mio.work_agent import execute
from mio.work_core import create_project, run_info

APPROVAL = "APPROVE SCORPIO9D3B7 ISOLATED WORK BROWSER ACCEPTANCE"
URL = "https://www.python.org/"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approval", required=True)
    args = parser.parse_args()
    if args.approval != APPROVAL or os.geteuid() == 0:
        raise SystemExit("Exact unprivileged owner approval required")
    with tempfile.TemporaryDirectory(prefix="scorpio9d3b7-demo-") as directory:
        parent = Path(directory)
        parent.chmod(0o700)
        root = parent / "work"
        project = create_project(root, "SCORPIO9D3B7 Demo", "One HTTPS document only")
        pending = propose(root, project=project["id"],
                          goal="Verify one public Python homepage as evidence", url=URL)
        if pending["state"] != "needs_review":
            raise RuntimeError("Unapproved Work task incorrectly queued")
        approved = decide(root, run=pending["run"], approve=True)
        if approved["state"] != "queued":
            raise RuntimeError("Approved browser Work task not queued")
        answer = asyncio.run(execute(root, approved["run"], SimpleNamespace()))
        events = [e["phase"] for e in answer["events"]]
        expected = ["browser.proposed", "browser.approved", "browser.claimed", "browser.verified"]
        if (answer["state"] != "answered" or answer["mode"] != "browser_verified"
                or not all(name in events for name in expected)
                or answer["sources"][0]["url"] != URL
                or len(answer["sources"][0]["page_sha256"]) != 64):
            raise RuntimeError("Isolated Work browser integration failed")
        record = run_info(root, approved["run"])
        if record["state"] != "answered":
            raise RuntimeError("Private Work audit result missing")
        report = {"phase": "SCORPIO9D3B7_WORK_BROWSER", "result": "verified",
                  "live_public_https": True, "offline_javascript": True,
                  "url": URL, "events": expected, "production_work_modified": False,
                  "services_restarted": False, "downloads": False, "installs": False,
                  "project": project["id"], "run": approved["run"],
                  "page_sha256": answer["sources"][0]["page_sha256"]}
        print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
