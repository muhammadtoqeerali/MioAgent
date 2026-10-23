"""AGENT6B project-local read-only source inspection and immutable audit receipts.

Designed for an explicit local owner command, not a remotely callable tool or a
live Work worker. No subprocess, model call, network call, source change or grant.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import stat
import time
import uuid
from pathlib import Path

from mio.agentic_plan_v06b import AgenticPreviewDenied, PreviewPlan, plan, validate_source

MAX_SOURCE_BYTES = 256_000
MAX_LEDGER_BYTES = 32_000
PLAN_FOLDER = (".mioagent-private", "agents", "audit", "agent6b")


def _safe_root(project: Path) -> Path:
    if not isinstance(project, Path) or not project.is_absolute() or project.is_symlink():
        raise AgenticPreviewDenied("Project root must be an absolute non-symlink")
    if not project.is_dir() or project.resolve() != project:
        raise AgenticPreviewDenied("Project root unavailable")
    return project


def _read_exact_source(project: Path, relative: str) -> bytes:
    """Read using openat and O_NOFOLLOW for each path segment, no path re-resolution."""
    validate_source(relative)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = os.O_RDONLY | os.O_DIRECTORY | nofollow
    descriptors: list[int] = []
    try:
        current = os.open(project, directory)
        descriptors.append(current)
        segments = relative.split("/")
        for segment in segments[:-1]:
            current = os.open(segment, directory, dir_fd=current)
            descriptors.append(current)
        fd = os.open(segments[-1], os.O_RDONLY | nofollow | os.O_NONBLOCK, dir_fd=current)
        descriptors.append(fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_SOURCE_BYTES:
            raise AgenticPreviewDenied("Unsafe source file kind or size")
        with os.fdopen(os.dup(fd), "rb") as handle:
            raw = handle.read(MAX_SOURCE_BYTES + 1)
        if len(raw) != info.st_size or len(raw) > MAX_SOURCE_BYTES:
            raise AgenticPreviewDenied("Source changed during bounded inspection")
        return raw
    except (OSError, OverflowError) as exc:
        raise AgenticPreviewDenied("Source file not available or unsafe") from exc
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def _structure(relative: str, raw: bytes) -> dict:
    try:
        content = raw.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise AgenticPreviewDenied("Non-UTF-8 source refused") from exc
    result: dict = {"path": relative, "bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "lines": len(content.splitlines()), "static_syntax": "not_applicable",
                    "definitions": []}
    if relative.endswith(".py"):
        try:
            tree = ast.parse(content, filename=relative)
        except SyntaxError as exc:
            result["static_syntax"] = "syntax_error"
            result["syntax_error_line"] = exc.lineno
        else:
            result["static_syntax"] = "parsed"
            result["definitions"] = [
                {"kind": "class" if isinstance(node, ast.ClassDef) else "function",
                 "name": node.name, "line": node.lineno}
                for node in tree.body
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            ][:80]
    return result


def inspect(project: Path, task: PreviewPlan) -> list[dict]:
    _safe_root(project)
    return [_structure(relative, _read_exact_source(project, relative))
            for relative in task.sources]


def _audit_directory(project: Path) -> Path:
    current = _safe_root(project)
    for name in PLAN_FOLDER:
        current = current / name
        if current.is_symlink():
            raise AgenticPreviewDenied("Symlink in project-local audit path")
        if not current.exists():
            try:
                current.mkdir(mode=0o700)
            except OSError as exc:
                raise AgenticPreviewDenied("Could not prepare project-local audit folder") from exc
        if not current.is_dir() or current.is_symlink():
            raise AgenticPreviewDenied("Invalid project-local audit folder")
    return current


def _new_receipt(path: Path, content: bytes) -> None:
    if len(content) > MAX_LEDGER_BYTES:
        raise AgenticPreviewDenied("Review receipt exceeds bounded limit")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    if path.read_bytes() != content:
        raise AgenticPreviewDenied("Receipt readback mismatch")


def execute_owner_preview(project: Path, goal: str, sources: tuple[str, ...] | list[str]) -> dict:
    """Execute exactly a static-inspection plan and write a review-ready receipt.

    Never call this from an autonomous worker: the caller must require explicit
    owner-terminal approval. This function alone has no permission-issuing power.
    """
    task = plan(goal, sources)
    details = inspect(project, task)
    receipt = {
        "format": 1,
        "phase": "AGENT6B",
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "needs_owner_review",
        "plan": task.record(),
        "inspection": details,
        "stages_completed": ["scope", "inspect", "analyze", "handoff"],
        "code_changed": False,
        "tests_executed": False,
        "persistent_grants_issued": False,
        "live_work_connected": False,
        "shell_or_network_used": False,
        "source_contents_stored": False,
        "limitations": "Static preview only; no claim of a fixed bug, applied patch or passing tests.",
    }
    data = (json.dumps(receipt, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()
    root = _audit_directory(project)
    label = "review-" + time.strftime("%Y%m%dT%H%M%SZ-", time.gmtime()) + uuid.uuid4().hex
    target = root / (label + ".json")
    _new_receipt(target, data)
    receipt["receipt_path"] = str(target)
    receipt["receipt_sha256"] = hashlib.sha256(data).hexdigest()
    return receipt
