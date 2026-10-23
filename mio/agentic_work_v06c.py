"""AGENT6C opt-in, owner-approved read-only Work inspection executor.

The Work API must authenticate the owner and store explicit sources; the worker
must have the matching opt-in environment flag. No model may request tools here.
No source writes, shells, network, persistent grants, or external folder access.
"""
from __future__ import annotations

import os
from pathlib import Path

from mio.agentic_plan_v06b import AgenticPreviewDenied, plan
from mio.agentic_preview_v06b import inspect

ENABLED_FLAG = "MIO_AGENT6C_INSPECTION_ENABLED"
PROJECT = Path(__file__).resolve().parents[1]
MAX_SUMMARY = 8000


def enabled() -> bool:
    """Exact opt-in, not a truthy interpretation of arbitrary env text."""
    return os.environ.get(ENABLED_FLAG) == "1"


def format_summary(task, details: list[dict]) -> str:
    """Create a bounded, evidence-only Work result. Never include file contents."""
    if len(details) != len(task.sources):
        raise AgenticPreviewDenied("Incomplete source inspection")
    lines = [
        "## Read-only MioAgent source inspection",
        "", "**Status:** needs owner review — no code was changed or executed.",
        f"**Goal category:** {task.kind}",
        f"**Source files inspected:** {len(details)}", "",
    ]
    for source, entry in zip(task.sources, details, strict=True):
        if source != entry.get("path"):
            raise AgenticPreviewDenied("Inspection source identity changed")
        digest = entry.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise AgenticPreviewDenied("Invalid source digest")
        syntax = entry.get("static_syntax")
        if syntax not in ("parsed", "syntax_error", "not_applicable"):
            raise AgenticPreviewDenied("Invalid static inspection status")
        lines.append(f"- `{source}` — SHA-256 `{digest}`; syntax: `{syntax}`; bytes: {int(entry['bytes'])}")
    lines.extend([
        "", "**Execution evidence:** Static source read and Python AST parsing only.",
        "**Not performed:** No patch, tests, host commands, network, grants or Git publication.",
        "**Next step:** Owner reviews the evidence and separately approves any proposed changes.",
    ])
    result = "\n".join(lines)
    if len(result) > MAX_SUMMARY:
        raise AgenticPreviewDenied("Inspection result exceeds size limit")
    return result


def execute_inspection_run(root: Path, run_id: str) -> dict:
    """Complete one authenticated Work queue entry under an explicit dual opt-in.

    This function is reached only by the worker's inspection_queued dispatch.
    Persistent Work state/events remain in the existing native Work database;
    the checked-out project is read-only from this function's perspective.
    """
    from mio import work_core

    record = work_core.run_info(root, run_id)
    if record["state"] != "queued" or record["mode"] != "inspection_queued":
        raise work_core.WorkStop("Only explicitly queued inspections may execute")
    if not enabled():
        work_core.event(root, run_id, "inspection.disabled", "Inspection opt-in is not active in Work worker")
        work_core.update(root, run_id, "needs_review", mode="inspection", result=(
            "Read-only inspection was not executed: the Work worker was not explicitly enabled. "
            "No workstation resources were accessed."
        ))
        return work_core.run_info(root, run_id)
    try:
        task = plan(record["prompt"], record["sources"])
        work_core.update(root, run_id, "running", mode="inspection")
        work_core.event(root, run_id, "inspection.scope", f"Owner-selected {len(task.sources)} allowlisted files")
        work_core.event(root, run_id, "inspection.plan", "Validate -> static read -> AST parse -> review; writes/tests blocked")
        details = inspect(PROJECT, task)
        for entry in details:
            work_core.event(root, run_id, "inspection.read", (
                f"{entry['path']} sha256={entry['sha256']} syntax={entry['static_syntax']}"))
        result = format_summary(task, details)
        work_core.event(root, run_id, "inspection.review", "Static evidence recorded; owner review required")
        work_core.update(root, run_id, "needs_review", mode="inspection", result=result)
    except Exception as exc:  # noqa: BLE001 - persistent Work jobs must terminate with an audit record
        work_core.event(root, run_id, "inspection.error", f"Static inspection blocked: {type(exc).__name__}")
        work_core.update(root, run_id, "failed", mode="inspection", error=(
            f"{type(exc).__name__}: bounded source inspection was not completed"))
    return work_core.run_info(root, run_id)
