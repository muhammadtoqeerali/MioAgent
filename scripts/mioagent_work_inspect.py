#!/usr/bin/env python3
"""AGENT6E: explicitly owner-approved, read-only MioAgent Work inspection client.

The only live write is one authenticated, pre-approved Work *task* created
by --mode submit. --mode preflight reads process health/status only.
Neither mode changes source files, runs host shell commands requested by a
model, activates a service, or grants broad workstation capabilities.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT = Path(__file__).resolve().parents[1]
# CLI entrypoints launched as scripts must resolve the checkout before importing mio.
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))
BASELINE = "69319d223fcfcee8983363e588e74292205cc2e4"
ORIGIN = "https://github.com/muhammadtoqeerali/MioAgent.git"
FLAG = "MIO_AGENT6C_INSPECTION_ENABLED"
ENDPOINT = "http://127.0.0.1:8000"
RUNTIME = Path(f"/var/tmp/mioagent-native-{os.getuid()}")
RECEIPTS = PROJECT / ".mioagent-private/agents/audit/agent6e"
SUBMIT_APPROVAL = "AGENT6E AUTHORIZE ONE AUTHENTICATED READ ONLY WORK INSPECTION"
READ_APPROVAL = "AGENT6E CHECK READ ONLY WORK INSPECTION READINESS"
MAX_REPLY = 150_000
ALLOWED_STATES = {"queued", "running", "needs_review", "answered", "failed", "interrupted"}
RUN_ID = re.compile(r"[0-9a-f]{32}\Z")

os.umask(0o077)
sys.dont_write_bytecode = True


class InspectionError(RuntimeError):
    """A preflight, approval or task-evidence gate was not satisfied."""


def require(value: bool, message: str) -> None:
    if not value:
        raise InspectionError(message)


def git_bytes(*args: str) -> bytes:
    p = subprocess.run(["git", "-C", str(PROJECT), *args], stdin=subprocess.DEVNULL,
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=8,
                       check=False)
    require(p.returncode == 0 and len(p.stdout) < 400_000, "Git source validation unavailable")
    return p.stdout


def validate_source_list(sources: list[str]) -> tuple[str, ...]:
    from mio.agentic_plan_v06b import AgenticPreviewDenied, plan
    try:
        result = plan("Review approved MioAgent source files without modifications", sources)
    except AgenticPreviewDenied as exc:
        raise InspectionError("Source allowlist rejected by published policy") from exc
    require(1 <= len(result.sources) <= 8, "Source list must contain 1–8 files")
    require(len(set(result.sources)) == len(result.sources), "Duplicate source paths denied")
    return tuple(result.sources)


def source_digests(sources: tuple[str, ...]) -> dict[str, str]:
    # Conservative operator workflow: inspect only bytes published in Git HEAD.
    # The server independently repeats file-type and symlink checks.
    from mio.agentic_preview_v06b import _read_exact_source
    digests = {}
    for source in sources:
        raw = _read_exact_source(PROJECT, source)
        require(raw == git_bytes("show", "HEAD:" + source),
                "Owner-selected source is not identical to published Git: " + source)
        digests[source] = hashlib.sha256(raw).hexdigest()
    return digests


def verified_service_flag(pid: int) -> bool:
    require(isinstance(pid, int) and pid > 1, "Invalid managed process")
    proc = Path(f"/proc/{pid}")
    require(proc.stat().st_uid == os.getuid(), "Managed service owner mismatch")
    require(Path(os.readlink(proc / "cwd")) == PROJECT, "Managed service working directory mismatch")
    data = (proc / "environ").read_bytes()
    require(len(data) <= 150_000, "Service environment unexpectedly large")
    # Only compare the exact flag; do not log or return secret-bearing environment.
    return sum(x == b"MIO_AGENT6C_INSPECTION_ENABLED=1" for x in data.split(b"\0")) == 1


def preflight_sources(sources: tuple[str, ...]) -> dict[str, str]:
    from scripts import manage_work_worker as worker
    from scripts import native_runtime as native
    require(os.getuid() == os.geteuid() != 0, "Refusing sudo/root or switched effective user")
    require(PROJECT == Path("/mnt/hdd16T/ToqeerHomeBackup/toqeer/MioAgent"),
            "Not the accepted MioAgent checkout")
    require(PROJECT.is_dir() and not PROJECT.is_symlink() and PROJECT.resolve() == PROJECT,
            "Unsafe project checkout")
    require(git_bytes("rev-parse", "HEAD").strip().decode() == BASELINE,
            "Published AGENT6C Git commit changed")
    require(git_bytes("branch", "--show-current").strip() == b"main", "Git branch changed")
    require(git_bytes("remote", "get-url", "origin").strip().decode() == ORIGIN,
            "GitHub origin changed")
    require(git_bytes("diff", "--cached", "--name-only", "-z") == b"", "Git staging not empty")
    for source in ("mio/work_api.py", "mio/work_core.py", "mio/work_agent.py",
                   "mio/agentic_work_v06c.py", "mio/agentic_plan_v06b.py", "mio/agentic_preview_v06b.py"):
        _ = source_digests((source,))
    api_pid = native.read_pid("api")
    worker_pid = worker.current()
    require(api_pid is not None and native.is_running("api"), "Managed API not recognized")
    require(worker_pid is not None, "Managed Work worker not recognized")
    require(verified_service_flag(api_pid) and verified_service_flag(worker_pid),
            "API and worker must both have inspection activated")
    token = native.get_token(create=False)
    require(isinstance(token, str) and len(token) >= 32, "Native API token unavailable")
    require(RECEIPTS.parent.is_dir() and not RECEIPTS.parent.is_symlink(),
            "Accepted audit vault boundary missing")
    return source_digests(sources)


def api_json(method: str, path: str, token: str, payload: dict | None = None) -> dict:
    require((method == "POST" and re.fullmatch(r"/api/work/projects/[0-9a-f]{32}/runs", path))
            or (method == "GET" and re.fullmatch(r"/api/work/runs/[0-9a-f]{32}", path)),
            "Unapproved API operation")
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
    require(body is None or len(body) <= 9000, "API request too large")
    req = Request(ENDPOINT + path, data=body, method=method, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/json",
        **({"Content-Type": "application/json"} if body is not None else {}),
    })
    try:
        with urlopen(req, timeout=5) as resp:
            require(resp.status in (200, 201, 202), "API rejected operation")
            raw = resp.read(MAX_REPLY + 1)
    except HTTPError as exc:
        # Never expose API error response or token (which might embed user data).
        raise InspectionError("API request denied (HTTP " + str(exc.code) + ")") from None
    except (OSError, URLError) as exc:
        raise InspectionError("Local Work API unavailable: " + type(exc).__name__) from None
    require(len(raw) <= MAX_REPLY, "Work API response exceeds size limit")
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise InspectionError("Invalid Work API response") from exc
    require(isinstance(result, dict), "Work API response must be an object")
    return result


def evaluate_run(run: dict, expected_sources: tuple[str, ...], digests: dict[str, str],
                 expected_id: str, expected_prompt: str) -> dict:
    require(run.get("id") == expected_id, "Work result identity mismatch")
    require(run.get("prompt") == expected_prompt, "Work prompt identity mismatch")
    require(run.get("mode") == "inspection", "Work mode mismatch")
    require(run.get("state") == "needs_review", "Work inspection did not complete for review")
    result = run.get("result")
    require(isinstance(result, str) and len(result) <= 8000, "Work result is absent or unbounded")
    phases = [x.get("phase") for x in run.get("events", []) if isinstance(x, dict)]
    require(phases.count("inspection.approved") == 1 and phases.count("inspection.plan") == 1 and
            phases.count("inspection.read") == len(expected_sources) and
            phases.count("inspection.review") == 1, "Durable inspection audit incomplete")
    require("no code was changed" in result.lower() and "no patch" in result.lower(),
            "Read-only inspection disclaimers missing")
    for source in expected_sources:
        require(result.count("`" + source + "`") == 1, "Missing unique source evidence: " + source)
        require(result.count("`" + digests[source] + "`") == 1,
                "Source evidence does not match pre-approved Git bytes: " + source)
    return {"run_id": expected_id, "state": "needs_review", "files": digests,
            "audit_phases": phases, "result_sha256": hashlib.sha256(result.encode()).hexdigest(),
            "status": "owner_review_required", "source_modified": False,
            "tools_granted": False, "code_executed": False}


def save_receipt(record: dict) -> Path:
    require(RECEIPTS.parent.is_dir() and not RECEIPTS.parent.is_symlink(),
            "Audit parent missing")
    if not RECEIPTS.exists():
        RECEIPTS.mkdir(mode=0o700)
    require(RECEIPTS.is_dir() and not RECEIPTS.is_symlink(), "Unsafe audit directory")
    payload = {"phase": "AGENT6E_OWNER_INSPECTION", "baseline": BASELINE, **record,
               "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    require(len(raw) < 12_000, "Audit receipt too large")
    dest = RECEIPTS / ("inspection-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) +
                       "-" + uuid.uuid4().hex + ".json")
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("preflight", "submit"), required=True)
    parser.add_argument("--approval", required=True)
    parser.add_argument("--project-id")
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--prompt", default="Review the specified MioAgent source files for maintainability")
    args = parser.parse_args(argv)
    require(args.approval == (SUBMIT_APPROVAL if args.mode == "submit" else READ_APPROVAL),
            "Exact owner authorization required")
    sources = validate_source_list(args.source or ["mio/work_agent.py", "mio/work_core.py"])
    require(isinstance(args.prompt, str) and 4 <= len(args.prompt) <= 3000,
            "Invalid bounded Work prompt")
    if args.mode == "submit":
        require(isinstance(args.project_id, str) and RUN_ID.fullmatch(args.project_id) is not None,
                "Explicit valid existing Work project ID is required")
    before_status = git_bytes("status", "--porcelain=v1", "-z", "--untracked-files=all")
    digests = preflight_sources(sources)
    print("PASS: published source, service identities and both inspection gates verified", flush=True)
    print("PASS: owner-selected source SHA-256 matches Git and safe allowlist", flush=True)
    if args.mode == "preflight":
        require(git_bytes("status", "--porcelain=v1", "-z", "--untracked-files=all") == before_status,
                "Git status changed during preflight")
        print("=== AGENT6E OWNER INSPECTION PREFLIGHT ACCEPTED; NO LIVE TASK ===", flush=True)
        return 0
    from scripts.native_runtime import get_token
    token = get_token(create=False)
    payload = {"prompt": args.prompt, "task_type": "inspection", "approved": True,
               "sources": list(sources)}
    run = api_json("POST", "/api/work/projects/" + args.project_id + "/runs", token, payload)
    run_id = run.get("id")
    require(isinstance(run_id, str) and RUN_ID.fullmatch(run_id) is not None and
            run.get("mode") == "inspection_queued", "Approved Work task was not queued")
    print("LIVE WORK: submitted read-only inspection run_id=" + run_id, flush=True)
    deadline = time.monotonic() + 45
    last = {}
    while time.monotonic() < deadline:
        last = api_json("GET", "/api/work/runs/" + run_id, token)
        if last.get("state") not in ("queued", "running"):
            break
        time.sleep(0.5)
    require(last.get("state") in ALLOWED_STATES and last.get("state") not in ("queued", "running"),
            "Work inspection still in progress; use Work UI to review by run ID")
    evidence = evaluate_run(last, sources, digests, run_id, args.prompt)
    require(source_digests(sources) == digests, "Work source changed during approved inspection")
    require(git_bytes("status", "--porcelain=v1", "-z", "--untracked-files=all") == before_status,
            "Unrelated Git status changed during inspection")
    receipt = save_receipt({**evidence, "project_id": args.project_id})
    print("PASS: real authenticated Work inspection and durable evidence verified", flush=True)
    print("=== AGENT6E OWNER WORK INSPECTION ACCEPTED; NEEDS REVIEW ===", flush=True)
    print("RUN ID: " + run_id, flush=True)
    print("RECEIPT: " + str(receipt), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (InspectionError, OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        # Never leak file contents, bearer tokens, URLs, or full response bodies.
        print("AGENT6E GUARDED STOP: " + type(exc).__name__ + ": " +
              (str(exc)[:160] if isinstance(exc, InspectionError) else "request unavailable"), flush=True)
        raise SystemExit(2) from None
