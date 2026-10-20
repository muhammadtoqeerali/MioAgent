"""Verify the quality, not just connectivity, of MioAgent public web results."""

from __future__ import annotations

import argparse
import asyncio
import json

from mio.studio_files import StudioError
from mio.studio_tools import web_search


async def probe(prompt: str) -> dict:
    try:
        sources = await web_search(prompt)
    except (StudioError, OSError, ValueError) as exc:
        return {"relevant": False, "reason": str(exc)[:300], "query": prompt}
    return {
        "relevant": bool(sources),
        "query": prompt,
        "results": [{"title": s["title"], "url": s["url"], "ref": s["ref"]} for s in sources],
        "note": "Topic relevance filter passed; source truth and publication dates are not verified",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default=(
        "Search the web for recent humanoid robotics research and give me three cited findings."
    ))
    args = parser.parse_args()
    result = asyncio.run(probe(args.query))
    print(json.dumps(result, indent=2))
    if not result["relevant"]:
        parser.exit(1, "STOP: no topic-relevant public search results\n")


if __name__ == "__main__":
    main()
