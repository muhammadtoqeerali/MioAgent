"""Diagnose public search reachability without model calls or exposing credentials."""

from __future__ import annotations

import asyncio
import json
import socket

import httpx

from mio.studio_files import StudioError
from mio.studio_tools import web_search

HOSTS = ("www.bing.com", "lite.duckduckgo.com")


async def probe() -> dict:
    data = {"dns": {}, "search": {"ok": False}}
    for host in HOSTS:
        try:
            data["dns"][host] = "resolves" if socket.getaddrinfo(host, 443) else "no addresses"
        except OSError as exc:
            data["dns"][host] = f"failed ({type(exc).__name__})"
    try:
        results = await web_search("Python 3 official documentation")
        data["search"] = {"ok": bool(results), "number_of_results": len(results),
                          "provider_url": results[0]["url"] if results else None}
    except (StudioError, httpx.HTTPError, OSError) as exc:
        data["search"] = {"ok": False, "reason": str(exc)[:240]}
    return data


def main():
    print(json.dumps(asyncio.run(probe()), indent=2))


if __name__ == "__main__":
    main()
