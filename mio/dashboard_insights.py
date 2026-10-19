"""Read-only, authenticated local intelligence summaries for the MioAgent dashboard.

Never accept arbitrary filesystem paths or run model inference. Exposes bounded
private run metadata and a separately requested verified patch to the local UI.
"""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException

from mio.model_fleet import inventory, load_policy

RUNTIME = Path(f"/var/tmp/mioagent-native-{os.getuid()}")
RUN_ID = re.compile(r"[0-9a-f]{64}\Z")
ENGINEERING_ID = re.compile(r"[0-9a-f]{64}(?:\.retry[0-9])?\.json\Z")
MAX_REPORT_SIZE = 150_000
MAX_PATCH_SIZE = 150_000


def _private_dir(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) & 0o077 == 0)


def _private_regular(path: Path, maximum: int) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) & 0o077 == 0
            and 0 <= info.st_size <= maximum)


def _read_report(path: Path) -> dict[str, Any] | None:
    if not _private_regular(path, MAX_REPORT_SIZE):
        return None
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    return data if isinstance(data, dict) else None


def list_repo_runs(root: Path = RUNTIME) -> list[dict[str, Any]]:
    parent = root / "repo-engineering"
    if not _private_dir(root) or not _private_dir(parent):
        return []
    results = []
    for item in sorted(parent.iterdir(), key=lambda p: p.name):
        if not RUN_ID.fullmatch(item.name) or not _private_dir(item):
            continue
        report = _read_report(item / "report.json")
        if not report or report.get("goal_sha256") != item.name:
            continue
        state = report.get("state")
        if state not in {"started", "passed", "failed", "stopped"}:
            continue
        attempts = report.get("attempts", [])
        if not isinstance(attempts, list):
            attempts = []
        sample = {
            "id": item.name,
            "state": state,
            "model": report.get("model") if isinstance(report.get("model"), str) else None,
            "planner_model": report.get("planner_model") if isinstance(report.get("planner_model"), str) else None,
            "tests_run": report.get("tests_run") if type(report.get("tests_run")) is int else 0,
            "baseline_passed": report.get("baseline", {}).get("passed") is True if isinstance(report.get("baseline"), dict) else None,
            "changed_files": attempts[-1].get("changed_files", []) if attempts and isinstance(attempts[-1], dict) else [],
            "attempt_count": len(attempts),
            "applied": "applied" in report,
            "patch_available": state == "passed" and _private_regular(item / "changes.patch", MAX_PATCH_SIZE),
            "created_unix": report.get("created_unix") if type(report.get("created_unix")) is int else None,
        }
        if not isinstance(sample["changed_files"], list):
            sample["changed_files"] = []
        sample["changed_files"] = [v for v in sample["changed_files"][:4] if isinstance(v, str) and len(v) <= 180]
        results.append(sample)
    return sorted(results, key=lambda d: d["created_unix"] or 0, reverse=True)[:20]


def list_goal_runs(root: Path = RUNTIME) -> list[dict[str, Any]]:
    parent = root / "engineering-runs"
    if not _private_dir(root) or not _private_dir(parent):
        return []
    results = []
    for path in sorted(parent.iterdir(), key=lambda p: p.name):
        if not ENGINEERING_ID.fullmatch(path.name):
            continue
        report = _read_report(path)
        if report is None:
            continue
        state = report.get("state")
        if state not in {"finished", "passed", "stopped", "failed", "started", "completed"}:
            continue
        results.append({
            "id": path.name,
            "state": state,
            "model": report.get("model") if isinstance(report.get("model"), str) else None,
            "project_id": report.get("project_id") if isinstance(report.get("project_id"), str) else None,
            "outcome": report.get("outcome") if isinstance(report.get("outcome"), str) else None,
        })
    return results[-20:][::-1]


def verified_patch(root: Path, run_id: str) -> dict[str, str]:
    if not RUN_ID.fullmatch(run_id):
        raise HTTPException(404, "Run not found")
    parent = root / "repo-engineering"
    run_dir = parent / run_id
    if not all(_private_dir(p) for p in (root, parent, run_dir)):
        raise HTTPException(404, "Run not found")
    report = _read_report(run_dir / "report.json")
    if not report or report.get("goal_sha256") != run_id or report.get("state") != "passed":
        raise HTTPException(404, "Verified patch not found")
    patch = run_dir / "changes.patch"
    if not _private_regular(patch, MAX_PATCH_SIZE):
        raise HTTPException(404, "Verified patch not found")
    try:
        return {"id": run_id, "patch": patch.read_text(encoding="utf-8")}
    except (OSError, UnicodeError) as exc:
        raise HTTPException(404, "Verified patch not found") from exc


def register_intelligence_routes(app: FastAPI, require_token: Callable[..., None]) -> None:
    """Register authenticated, read-only routes on the existing private FastAPI app."""

    @app.get("/api/intelligence/overview", dependencies=[Depends(require_token)])
    async def intelligence_overview() -> dict[str, Any]:
        found: dict[str, dict] = {}
        warning = None
        try:
            found = await inventory()
        except Exception:  # noqa: BLE001 - optional read-only telemetry, never fail the dashboard
            warning = "Local Ollama inventory unavailable"
        try:
            policy = load_policy()
        except (ValueError, OSError):
            policy = None
            warning = "Fleet policy unavailable or invalid"
        return {
            "release": "v0.4F",
            "models": [{"id": name, "size_bytes": meta.get("size_bytes"),
                        "selected": policy is not None and name in policy.installed_fingerprints}
                       for name, meta in sorted(found.items())],
            "fleet_active": policy is not None,
            "routes": {key: list(value) for key, value in policy.roles.items()} if policy else {},
            "repo_runs": list_repo_runs(RUNTIME),
            "goal_runs": list_goal_runs(RUNTIME),
            "warning": warning,
            "capabilities": {
                "repository_inspection": True,
                "bounded_python_edits": True,
                "immutable_acceptance": True,
                "cross_model_review": True,
                "browser_automation": False,
                "voice_control": False,
                "unrestricted_tools": False,
            },
            "read_only": True,
        }

    @app.get("/api/intelligence/repository/{run_id}/patch", dependencies=[Depends(require_token)])
    def intelligence_patch(run_id: str) -> dict[str, str]:
        return verified_patch(RUNTIME, run_id)
