"""Local Ollama role evaluation, opt-in by model ID; cannot pull or activate models."""

from __future__ import annotations

import argparse
import asyncio

from mio.autonomy_eval import evaluate, write_report
from mio.model_fleet import inventory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inventory", "run"))
    parser.add_argument("--models", nargs="+", default=[])
    args = parser.parse_args()
    if args.command == "inventory":
        found = asyncio.run(inventory())
        for model, data in sorted(found.items()):
            print(model, data["digest"][:14], round((data["size_bytes"] or 0) / 1e9, 2), "GB")
        print("No benchmark inference, model download or role switch performed.")
        return
    if not args.models:
        parser.error("run requires --models with one to three installed local model IDs")
    report = asyncio.run(evaluate(args.models))
    target = write_report(report)
    print("Benchmark report:", target)
    for name in args.models:
        items = [r for r in report["results"] if r["model"] == name]
        print(name, "scored", sum(x["score"] for x in items), "/", len(items),
              "latency seconds:", round(sum(x["latency_s"] for x in items), 2),
              "failures:", sum(x["failure"] is not None for x in items))
    print("These are four small format probes, NOT state-of-the-art comparisons.")
    print("No role selection, model download, Git modification or model promotion occurred.")


if __name__ == "__main__":
    main()
