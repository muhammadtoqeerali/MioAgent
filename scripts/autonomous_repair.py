"""Opt-in bounded repair runner for MioAgent v0.3C local API.

Runs only existing approved-test, immutable-test workflows. No shell command
execution or remote APIs. CLI entrypoint: python -m scripts.autonomous_repair.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = "http://127.0.0.1:8000/api"
ID_PATTERN = re.compile(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\Z")
MAX_ATTEMPTS = 3
POLL_SECONDS = 2
TIMEOUT_SECONDS = 240


class RunStopped(RuntimeError):
    """No further autonomous actions may run."""


def test_fingerprints(project: dict) -> dict[str, str]:
    """Rehash test bytes from API data; never trust model-supplied hashes alone."""
    draft = project.get("draft") or {}
    result = {}
    for item in draft.get("files", []):
        path = item.get("path", "")
        if Path(path).name.startswith("test_") and path.endswith(".py"):
            raw = item["content"].encode("utf-8")
            if hashlib.sha256(raw).hexdigest() != item.get("sha256"):
                raise RunStopped("API draft test hash mismatch")
            result[path] = hashlib.sha256(raw).hexdigest()
    if not result:
        raise RunStopped("No approved test_*.py acceptance tests")
    return result


def verify_source_policy(previous: dict, revision: dict, immutable: dict[str, str]) -> None:
    """Reject test edits, added/removed files, and excessive source changes."""
    before = {f["path"]: f for f in previous["draft"]["files"]}
    after = {f["path"]: f for f in revision["draft"]["files"]}
    if before.keys() != after.keys():
        raise RunStopped("Repair revision changed project file inventory")
    if test_fingerprints(revision) != immutable:
        raise RunStopped("Repair revision changed acceptance tests")
    changed = []
    for path, file in after.items():
        raw = file["content"].encode("utf-8")
        if len(raw) > 16 * 1024 or hashlib.sha256(raw).hexdigest() != file.get("sha256"):
            raise RunStopped("Invalid revision content hash or size")
        if file["sha256"] != before[path]["sha256"]:
            changed.append(path)
    if not 1 <= len(changed) <= 2 or any(
        not path.endswith(".py") or Path(path).name.startswith("test_") for path in changed
    ):
        raise RunStopped("Repair changed unapproved source files")


class LocalAPI:
    def __init__(self, token: str):
        self.token = token

    def call(self, path: str, *, post: bool = False) -> dict:
        if not re.fullmatch(r"[a-z0-9/_-]+", path):
            raise RunStopped("Unexpected API path")
        payload = json.dumps({"approved": True}).encode() if post else None
        request = Request(
            f"{BASE}/{path}",
            data=payload,
            method="POST" if post else "GET",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=20) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            raise RunStopped(f"Local API operation failed: {path}: {exc}") from exc


def wait_task(api: LocalAPI, path: str, *, timeout: int = TIMEOUT_SECONDS) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = api.call(path)
        state = result.get("status")
        if state in {"completed", "failed", "canceled", "promoted"}:
            if state != "completed":
                raise RunStopped(f"Task {path} stopped: {state}: {result.get('error', '')[:300]}")
            return result
        if state not in {"queued", "running"}:
            raise RunStopped(f"Unexpected task status: {state}")
        time.sleep(POLL_SECONDS)
    raise RunStopped(f"Timed out awaiting {path}")


def run_cycle(api: LocalAPI, project_id: str, *, attempts: int = MAX_ATTEMPTS, report=None) -> dict:
    if not ID_PATTERN.fullmatch(project_id) or not 1 <= attempts <= MAX_ATTEMPTS:
        raise RunStopped("Invalid project ID or repair limit")
    status = api.call("status")
    if not status.get("project_mode_enabled") or not status.get("sandbox_verify_enabled"):
        raise RunStopped("Project Mode and Bubblewrap verification must be enabled")
    original = api.call(f"projects/{project_id}")
    if original.get("status") != "completed":
        raise RunStopped("Project must already be approved and completed")
    immutable = test_fingerprints(original)
    current_id = project_id
    history = []

    def record(step: dict) -> None:
        history.append(step)
        if report:
            report({"source_project": project_id, "current_project": current_id,
                    "immutable_test_sha256": immutable, "history": history,
                    "timestamp": time.time()})

    for attempt in range(attempts + 1):
        verification = api.call(f"projects/{current_id}/verification")
        if verification.get("status") != "completed":
            if verification.get("status") in {"queued", "running"}:
                verification = wait_task(api, f"projects/{current_id}/verification")
            elif verification.get("status") == "not_run":
                api.call(f"projects/{current_id}/verify", post=True)
                verification = wait_task(api, f"projects/{current_id}/verification")
            else:
                raise RunStopped("Existing verifier state not safe to reuse")
        result = verification.get("result") or {}
        if result.get("executed") is not True:
            raise RunStopped("Verification did not execute")
        if result.get("passed") is True and result.get("outcome") == "passed" and result.get("tests_run", 0) > 0:
            record({"attempt": attempt, "project": current_id, "outcome": "passed",
                    "tests_run": result["tests_run"]})
            return {"outcome": "passed", "project_id": current_id, "attempts": attempt, "history": history}
        if result.get("outcome") != "failed" or result.get("passed") is not False:
            raise RunStopped("Not eligible for model repair; failure may be infrastructure related")
        record({"attempt": attempt, "project": current_id, "outcome": "failed",
                "tests_run": result.get("tests_run", 0)})
        if attempt == attempts:
            return {"outcome": "repair_limit", "project_id": current_id, "attempts": attempt,
                    "history": history}
        proposal = api.call(f"projects/{current_id}/repair")
        if proposal.get("status") == "not_run":
            api.call(f"projects/{current_id}/repair", post=True)
            proposal = wait_task(api, f"projects/{current_id}/repair")
        elif proposal.get("status") in {"queued", "running"}:
            proposal = wait_task(api, f"projects/{current_id}/repair")
        elif proposal.get("status") != "completed":
            raise RunStopped("Repair proposal not reusable; manual investigation required")
        data = proposal.get("result") or {}
        if not data.get("review_required") or data.get("executed") is not False:
            raise RunStopped("Repair proposal did not request review")
        previous = api.call(f"projects/{current_id}")
        revision = api.call(f"projects/{current_id}/repair/use", post=True)
        if revision.get("status") != "review":
            raise RunStopped("Repair revision not in review state")
        verify_source_policy(previous, revision, immutable)
        # Explicit CLI --execute delegates approval only for this bounded revision.
        api.call(f"projects/{revision['id']}/apply", post=True)
        deadline = time.monotonic() + TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            applied = api.call(f"projects/{revision['id']}")
            if applied.get("status") == "completed":
                break
            if applied.get("status") not in {"review", "applying"}:
                raise RunStopped("Revision application did not complete")
            time.sleep(POLL_SECONDS)
        else:
            raise RunStopped("Revision application timed out")
        if test_fingerprints(applied) != immutable:
            raise RunStopped("Applied revision changed acceptance tests")
        current_id = revision["id"]
        record({"attempt": attempt + 1, "project": current_id, "outcome": "approved_revision"})
    raise RunStopped("Unexpected repair loop state")


def save_atomic_private(path: Path, value: dict) -> None:
    if path.is_symlink() or not path.parent.is_dir() or path.parent.is_symlink():
        raise RunStopped("Unsafe report path")
    dirstat = path.parent.stat()
    if dirstat.st_uid != os.getuid() or stat.S_IMODE(dirstat.st_mode) & 0o077:
        raise RunStopped("Report directory must be owned by user and mode 0700")
    temp = path.with_name(path.name + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_id", help="UUID of existing approved project")
    parser.add_argument("--execute", action="store_true", help="Grant bounded source revision approval")
    parser.add_argument("--max-repairs", type=int, default=2, choices=range(1, 4))
    args = parser.parse_args()
    if not args.execute:
        raise SystemExit("Refusing to run: add --execute for this exact approved project ID")
    from scripts.native_runtime import RUNTIME, get_token, setup_runtime

    setup_runtime()
    reports = RUNTIME / "repair-runs"
    reports.mkdir(mode=0o700, exist_ok=True)
    if not ID_PATTERN.fullmatch(args.project_id):
        raise SystemExit("Invalid project identifier")
    out = reports / f"{args.project_id}.json"
    if out.exists():
        raise SystemExit("Report already exists for this project. Refusing replay; review it first.")
    try:
        result = run_cycle(
            LocalAPI(get_token()), args.project_id, attempts=args.max_repairs,
            report=lambda data: save_atomic_private(out, data),
        )
        save_atomic_private(out, {**result, "finished": True})
        print(json.dumps(result, indent=2))
        print("Report:", out)
    except (RunStopped, OSError) as exc:
        print(f"STOPPED: {exc}")
        print("Inspect Project Mode and private run report; no automatic retry.")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
