"""SCORPIO9C5: independent real-worker/Bubblewrap acceptance on synthetic private data.

The entrypoint never targets production Work data or the managed worker. The
synthetic fixture uses the deterministic internal grant-staging function for
tests only; it does NOT purport to obtain owner approval for production tasks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from mio.scorpio9c3_step_grants import _stage, expected_prompt
from mio.supervisor_core import approve_plan, create_plan
from mio.work_core import RUNTIME, WorkStop, create_project, db

APPROVAL = "APPROVE SCORPIO9C5 ISOLATED WORKER ACCEPTANCE NO PRODUCTION TASKS"
CASES = ("sequential", "revoked", "expired", "changed", "unbound")
MAX_CASE_SECONDS = 25
PROJECT_SOURCE = Path(__file__).resolve().parents[1]


def _owner_private(folder: Path) -> None:
    st = folder.lstat()
    if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid()
            or stat.S_IMODE(st.st_mode) & 0o077 or folder.is_symlink()):
        raise WorkStop("Isolated acceptance directory is not owner-private")


def _case_root(parent: Path, label: str) -> tuple[Path, Path]:
    """Construct ONLY a fresh synthetic Work/input tree under a caller-owned root."""
    if label not in CASES:
        raise WorkStop("Unknown acceptance case")
    _owner_private(parent)
    case = parent / label
    case.mkdir(mode=0o700)
    _owner_private(case)
    base = case / "tool-inputs"
    base.mkdir(mode=0o700)
    _owner_private(base)
    return case / "work", base


def _prepare(root: Path, base: Path, label: str) -> dict:
    project = create_project(root, "Isolated acceptance only", "Synthetic offline data only")
    folder = base / project["id"]
    folder.mkdir(mode=0o700)
    _owner_private(folder)
    filenames = ("a.txt", "b.txt") if label == "sequential" else ("a.txt",)
    contents = {}
    for name in filenames:
        raw = ("scorpio9c5 isolated fixture " + name + "\n").encode("ascii")
        (folder / name).write_bytes(raw)
        contents[name] = hashlib.sha256(raw).hexdigest()
    plan = create_plan(
        root, project["id"], "Verify isolated worker and scoped one-use tools",
        [expected_prompt(name) for name in filenames],
    )
    grants = []
    if label != "unbound":
        for step, name in zip(plan["steps"], filenames, strict=True):
            grants.append(_stage(root, project["id"], plan["id"], step["id"], name))
    if label in ("revoked", "expired"):
        with db(root) as conn:
            if label == "revoked":
                conn.execute("UPDATE scorpio9c_grants SET revoked=1 WHERE id=?",
                             (grants[0]["grant_id"],))
            else:
                conn.execute("UPDATE scorpio9c_grants SET expires=0 WHERE id=?",
                             (grants[0]["grant_id"],))
    if label == "changed":
        (folder / "a.txt").write_bytes(b"input changed AFTER synthetic grant staging\n")
    approve_plan(root, plan["id"])
    return {"plan": plan["id"], "files": contents, "grants": grants}


def _child_environment() -> dict[str, str]:
    """Never pass workstation secrets, cloud credentials or ambient model routing."""
    return {
        "HOME": str(Path.home()),
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "MIO_API_TOKEN": "SCORPIO9C5_SYNTHETIC_TEST_ONLY_NO_API_REQUESTS_2026",
        "MIO_ALLOW_CLOUD": "false",
        "MIO_MODEL_ROUTE": "local",
        "MIO_LOCAL_MODEL": "",
        "MIO_LOCAL_BASE_URL": "http://127.0.0.1:11434/v1",
        "MIO_CLOUD_API_KEY": "",
    }


def _spawn_worker(root: Path) -> subprocess.Popen:
    """Starts an un-managed child against the explicit synthetic root, not WORK_ROOT."""
    source = (
        "import asyncio,sys;from pathlib import Path;"
        "from mio.work_worker import serve;"
        "asyncio.run(serve(Path(sys.argv[1]),poll_seconds=0.07))"
    )
    return subprocess.Popen(
        [sys.executable, "-B", "-c", source, str(root)],
        cwd=PROJECT_SOURCE, env=_child_environment(), stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, close_fds=True,
        start_new_session=True,
    )


def _snapshot(root: Path, plan_id: str) -> dict:
    with db(root) as conn:
        plan = conn.execute("SELECT state FROM supervisor_plans WHERE id=?",
                            (plan_id,)).fetchone()
        if not plan:
            raise WorkStop("Synthetic plan unavailable")
        steps = [dict(r) for r in conn.execute(
            "SELECT id,state,run_id FROM supervisor_steps WHERE plan=? ORDER BY position",
            (plan_id,),
        )]
        runs = [dict(r) for r in conn.execute(
            "SELECT r.id,r.state,r.mode,r.result FROM runs r "
            "JOIN supervisor_steps s ON s.run_id=r.id "
            "WHERE s.plan=? ORDER BY s.position", (plan_id,),
        )]
        events = [r[0] for r in conn.execute(
            "SELECT e.phase FROM events e JOIN runs r ON e.run=r.id "
            "JOIN supervisor_steps s ON s.run_id=r.id "
            "WHERE s.plan=? ORDER BY e.id", (plan_id,),
        )]
        # An unstaged owner step intentionally has no grant table yet.
        # Snapshotting must be read-only with respect to the grant schema:
        # the worker may create that table after this first observation.
        grant_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='scorpio9c_grants'"
        ).fetchone()
        grants = ([dict(r) for r in conn.execute(
            "SELECT id,used,revoked FROM scorpio9c_grants ORDER BY created,id",
        )] if grant_table else [])
        return {"plan": plan["state"], "steps": steps, "runs": runs,
                "events": events, "grants": grants}


def _verify(result: dict, fixture: dict, label: str) -> dict:
    runs, steps, grants = result["runs"], result["steps"], result["grants"]
    if label == "sequential":
        if (result["plan"] != "complete" or len(runs) != 2
                or len({row["id"] for row in runs}) != 2
                or not all(row["state"] == "answered" and row["mode"] == "tool_sha256"
                           for row in runs)
                or not all(step["state"] == "done" for step in steps)
                or [row["used"] for row in grants] != [1, 1]
                or result["events"].count("tool.claimed") != 2
                or result["events"].count("tool.verified") != 2):
            raise WorkStop("Sequential worker acceptance evidence mismatch")
        queued = [i for i, phase in enumerate(result["events"]) if phase == "queued"]
        verified = [i for i, phase in enumerate(result["events"]) if phase == "tool.verified"]
        if (len(queued) != 2 or len(verified) != 2
                or not queued[0] < verified[0] < queued[1] < verified[1]):
            raise WorkStop("Second tool step queued before first was verified")
        for row, sha in zip(runs, fixture["files"].values(), strict=True):
            if row["result"] != "Verified offline SHA-256: " + sha:
                raise WorkStop("Worker output does not match independently hashed fixture")
    else:
        if (result["plan"] != "attention" or len(runs) != 1
                or runs[0]["state"] != "needs_review"
                or runs[0]["mode"] != "tool_denied"
                or runs[0]["result"] is not None
                or steps[0]["state"] != "attention"
                or result["events"].count("tool.denied") != 1
                or any(x in result["events"] for x in ("tool.claimed", "tool.verified"))
                or any(row["used"] for row in grants)):
            raise WorkStop("Denied tool was executed or not durably halted")
    return {"case": label, "plan_state": result["plan"],
            "run_states": [row["state"] for row in runs],
            "sandbox_successes": result["events"].count("tool.verified"),
            "denials": result["events"].count("tool.denied"),
            "grant_uses": sum(int(row["used"]) for row in grants)}


def trial(parent: Path, label: str) -> dict:
    """Real worker process + real Bubblewrap, never the production worker."""
    if not shutil.which("bwrap") or not Path("/usr/bin/sha256sum").is_file():
        raise WorkStop("Mandatory Bubblewrap and system SHA-256 tool unavailable")
    root, base = _case_root(parent, label)
    fixture = _prepare(root, base, label)
    child = _spawn_worker(root)
    prior_failure = False
    try:
        until = time.monotonic() + MAX_CASE_SECONDS
        expected = "complete" if label == "sequential" else "attention"
        while time.monotonic() < until:
            if child.poll() is not None:
                raise WorkStop("Isolated Work worker terminated unexpectedly")
            evidence = _snapshot(root, fixture["plan"])
            if evidence["plan"] == expected:
                summary = _verify(evidence, fixture, label)
                # Confirm repeated idle dispatch does not enqueue duplicate runs.
                time.sleep(0.2)
                later = _snapshot(root, fixture["plan"])
                if later != evidence:
                    raise WorkStop("Supervisor retried or changed settled run state")
                return summary
            time.sleep(0.10)
        raise WorkStop("Isolated worker did not settle within the acceptance budget")
    except BaseException:
        prior_failure = True
        raise
    finally:
        # If the child has not installed its signal handler yet, our explicit
        # SIGTERM may terminate it with -SIGTERM. That is a valid test teardown,
        # not evidence that the worker failed during the acceptance operation.
        sent_term = child.poll() is None
        if sent_term:
            child.send_signal(signal.SIGTERM)  # Only our known Popen child.
        killed = False
        try:
            child.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()  # Only our known synthetic child, never production.
            child.communicate(timeout=5)
            killed = True
        # Never overwrite a genuine assertion/SQLite/sandbox failure with a
        # secondary teardown failure. Check unexpected exit if trial succeeded.
        permitted = (0, -signal.SIGTERM) if sent_term else (0,)
        if not prior_failure and (killed or child.returncode not in permitted):
            raise WorkStop("Synthetic Work worker did not exit cleanly")


def _ensure_private_runtime() -> Path:
    _owner_private(RUNTIME)
    parent = RUNTIME / "scorpio9c5-acceptance"
    if parent.is_symlink():
        raise WorkStop("Isolated acceptance parent is a symlink")
    parent.mkdir(mode=0o700, exist_ok=True)
    _owner_private(parent)
    return parent


def isolated_acceptance() -> dict:
    """Each scenario uses a separate, freshly generated Work DB and test files."""
    parent = _ensure_private_runtime()
    with tempfile.TemporaryDirectory(prefix="session-", dir=parent) as session:
        private = Path(session)
        _owner_private(private)
        cases = [trial(private, name) for name in CASES]
    return {"release": "SCORPIO9C5", "mode": "isolated_real_worker",
            "outcome": "accepted", "cases": cases,
            "production_work_modified": False, "managed_services_restarted": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("isolated",))
    parser.add_argument("--approval", required=True)
    args = parser.parse_args()
    if args.approval != APPROVAL:
        parser.error("Explicit isolated acceptance approval does not match")
    try:
        result = isolated_acceptance()
    except (WorkStop, OSError, sqlite3.DatabaseError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"SCORPIO9C5 ISOLATED ACCEPTANCE DENIED: {type(exc).__name__}") from exc
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
