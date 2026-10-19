"""Explicit workstation-owner registration of a Python goal for dashboard jobs.

Usage: python -m scripts.register_repo_goal /absolute/path/to/existing-goal.json
Registration does NOT run a model or modify the source repository.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mio.dashboard_jobs import register_goal
from mio.repo_agent import RepoStop
from scripts.native_runtime import setup_runtime


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("goal", type=Path)
    args = parser.parse_args()
    try:
        setup_runtime()
        print(json.dumps(register_goal(args.goal), indent=2))
    except (RepoStop, ValueError, OSError) as exc:
        parser.exit(1, f"STOP: {exc}\n")


if __name__ == "__main__":
    main()
