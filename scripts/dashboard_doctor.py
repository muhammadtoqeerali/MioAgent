"""Read-only local dashboard checks. Does not print private tokens or modify services."""

from __future__ import annotations

import argparse
import socket
import subprocess
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import native_runtime


def check(url: str, marker: bytes | None = None) -> bool:
    try:
        with urlopen(url, timeout=4) as response:
            code = response.status
            body = response.read(80000)
        valid = code == 200 and (marker is None or marker.lower() in body.lower())
        print(f"{'PASS' if valid else 'FAIL'} {url}: HTTP {code}, expected page content: {valid}")
        return valid
    except (OSError, HTTPError, URLError) as exc:
        print(f"FAIL {url}: {type(exc).__name__}: {exc}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print("=== MioAgent workstation browser-access diagnostic ===")
    print(f"Host: {socket.gethostname()}")
    print("These URLs work only inside this machine's network namespace.")
    native_runtime.status()
    print("\nGET checks (not HEAD):")
    results = [
        check("http://127.0.0.1:8000/health", b'"ok":true'),
        check("http://127.0.0.1:3000/", b"MioAgent"),
        check("http://127.0.0.1:3000/api/proxy/status", b'"version"'),
    ]
    print("\nLocal listeners (read-only):")
    try:
        proc = subprocess.run(
            ["ss", "-ltnp"], check=False, capture_output=True, text=True, timeout=5
        )
        for line in proc.stdout.splitlines():
            if ":3000" in line or ":8000" in line:
                print(line)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"Listeners unavailable: {exc}")
    if all(results):
        print("\nPASS: Both services and the dashboard proxy respond on THIS workstation.")
        print("If your browser still refuses 127.0.0.1, check whether it runs on another")
        print("computer or an isolated environment. Do not expose API port 8000 to LAN.")
        return 0
    print("\nFAIL: Inspect services with: python3 scripts/native_runtime.py logs")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
