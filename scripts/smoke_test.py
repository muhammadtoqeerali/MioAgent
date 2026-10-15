"""Local deployment smoke test using only Python standard library.

Requires that the API container is running on http://127.0.0.1:8000.
Does not print the credential, create external network traffic, or access the cloud.
"""
import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def load_token() -> str:
    secret_file = Path.home() / ".config" / "mioagent" / ".env"
    values = {}
    for line in secret_file.read_text().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    token = values.get("MIO_API_TOKEN") or os.environ.get("MIO_API_TOKEN")
    if not token:
        raise RuntimeError("API token missing; run python3 scripts/init_env.py")
    return token


def request(path: str, token: str | None = None, body: dict | None = None) -> dict:
    raw = json.dumps(body).encode() if body is not None else None
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if raw is not None:
        headers["Content-Type"] = "application/json"
    req = Request("http://127.0.0.1:8000" + path, data=raw, headers=headers)
    with urlopen(req, timeout=8) as response:
        return json.loads(response.read().decode())


def main() -> None:
    token = load_token()
    print("[1/4] Checking API health ...")
    assert request("/health")["ok"] is True
    print("[2/4] Checking authenticated service state ...")
    status = request("/api/status", token)
    assert status["version"] == "0.1.0"
    assert status["ai_model_connected"] is False
    print("[3/4] Creating genuine persisted echo task ...")
    task = request("/api/tasks", token, {"kind": "echo", "prompt": "MioAgent smoke test"})
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        latest = request("/api/tasks/" + task["id"], token)
        if latest["status"] == "completed":
            assert latest["result"]["text"] == "MioAgent smoke test"
            break
        if latest["status"] == "failed":
            raise RuntimeError("Worker failed: " + str(latest["error"]))
        time.sleep(0.5)
    else:
        raise TimeoutError("Worker did not complete echo task within 15 seconds")
    print("[4/4] Checking task listing ...")
    ids = {row["id"] for row in request("/api/tasks", token)["tasks"]}
    assert task["id"] in ids
    print("PASS: API authentication, PostgreSQL-backed queue, background execution and result persistence")


if __name__ == "__main__":
    try:
        main()
    except (OSError, HTTPError, URLError, AssertionError, KeyError, TimeoutError) as exc:
        raise SystemExit(f"FAIL: {exc}") from exc
