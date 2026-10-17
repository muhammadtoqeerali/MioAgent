"""Inspect candidate models/skills and dry-run their routing (offline only)."""

from __future__ import annotations

import argparse
import json

from mio.capability_registry import inventory, recommend


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=["chat", "coding", "planning", "review", "research", "diagram"])
    parser.add_argument("--installed-model", action="append", default=None,
                        help="Explicitly verified local model ID; repeat as needed")
    parser.add_argument("--audited-skill", action="append", default=[],
                        help="Skill ID already audited separately; dry-run only")
    args = parser.parse_args()
    if args.role:
        installed = tuple(args.installed_model) if args.installed_model is not None else ("gpt-oss:20b",)
        result = recommend(args.role, installed_models=installed,
                           audited_skills=frozenset(args.audited_skill))
    else:
        result = inventory()
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
