"""AGENT6B: deterministic, bounded multi-step plans for owner-initiated Work previews.

No generated action is authority to access the host. Plans cannot approve tools,
run terminal commands, start workers, or mutate published source.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

MAX_GOAL = 3000
MAX_SOURCES = 8
DEFAULT_SOURCES = (
    "mio/work_agent.py",
    "mio/work_core.py",
    "mio/work_api.py",
    "mio/work_worker.py",
)
PATH = re.compile(r"[A-Za-z0-9_.\-/]{1,160}\Z")
GOAL_KINDS = (
    ("repair", re.compile(r"\b(?:fix|bug|repair|debug|failing|exception)\b", re.IGNORECASE)),
    ("implement", re.compile(r"\b(?:build|create|implement|develop|feature|connect)\b", re.IGNORECASE)),
    ("audit", re.compile(r"\b(?:audit|security|review|inspect|check|analy[sz]e)\b", re.IGNORECASE)),
)
DENIED_SEGMENTS = frozenset({
    ".git", ".mioagent-private", "node_modules", ".next", "__pycache__",
    "secrets", "credentials", "private", "models", "backups", "downloads",
    ".cache", "venv", ".venv", "dist", "build",
})
ALLOWED_ROOTS = frozenset({"mio", "tests", "scripts", "docs"})
ALLOWED_EXTENSIONS = frozenset({".py", ".md", ".ts", ".tsx"})


class AgenticPreviewDenied(ValueError):
    """No implied access or approval when a bounded preview is rejected."""


@dataclass(frozen=True)
class PreviewPlan:
    version: int
    goal: str
    goal_sha256: str
    kind: str
    sources: tuple[str, ...]
    stages: tuple[dict[str, str], ...]
    requested_capabilities: tuple[str, ...]
    approved_capabilities: tuple[str, ...]

    def record(self) -> dict:
        return {
            "version": self.version,
            "goal": self.goal,
            "goal_sha256": self.goal_sha256,
            "kind": self.kind,
            "sources": list(self.sources),
            "stages": list(self.stages),
            "requested_capabilities": list(self.requested_capabilities),
            "approved_capabilities": list(self.approved_capabilities),
        }


def validate_source(name: str) -> str:
    if not isinstance(name, str) or not PATH.fullmatch(name) or "\\" in name:
        raise AgenticPreviewDenied("Invalid source path")
    parts = name.split("/")
    if (len(parts) < 2 or parts[0] not in ALLOWED_ROOTS or
            any(not p or p in (".", "..") or p.startswith(".") or
                p.lower() in DENIED_SEGMENTS for p in parts)):
        raise AgenticPreviewDenied("Private or unsafe source path denied")
    suffix = "." + parts[-1].rsplit(".", 1)[-1] if "." in parts[-1] else ""
    if suffix not in ALLOWED_EXTENSIONS:
        raise AgenticPreviewDenied("Unsupported source file extension")
    return name


def plan(goal: str, sources: tuple[str, ...] | list[str] = DEFAULT_SOURCES) -> PreviewPlan:
    if not isinstance(goal, str) or not (8 <= len(goal.strip()) <= MAX_GOAL):
        raise AgenticPreviewDenied("Goal must be 8–3000 characters")
    if any(ord(c) < 32 and c not in "\n\t" for c in goal):
        raise AgenticPreviewDenied("Control characters in goal are forbidden")
    if not isinstance(sources, (list, tuple)) or not 1 <= len(sources) <= MAX_SOURCES:
        raise AgenticPreviewDenied("Select between one and eight explicit source files")
    names = tuple(validate_source(s) for s in sources)
    if len(set(names)) != len(names):
        raise AgenticPreviewDenied("Duplicate source file")
    kind = next((label for label, pattern in GOAL_KINDS if pattern.search(goal)), "explore")
    stages = (
        {"id": "scope", "operation": "goal.validate", "status": "planned",
         "acceptance": "Bounded owner-provided goal and explicit source allowlist"},
        {"id": "inspect", "operation": "repo.inspect.readonly", "status": "planned",
         "acceptance": "Record SHA-256, size and static Python structure for every selected source"},
        {"id": "analyze", "operation": "static.ast.parse", "status": "planned",
         "acceptance": "Detect syntax errors without executing, importing or modifying source"},
        {"id": "handoff", "operation": "owner.review", "status": "planned",
         "acceptance": "Write an immutable review receipt, explicitly without test or code-change claims"},
        {"id": "future", "operation": "approval.required", "status": "blocked",
         "acceptance": "Writing code, running tests and publishing require separate grants and release gates"},
    )
    normalized = goal.strip()
    return PreviewPlan(
        1, normalized, hashlib.sha256(normalized.encode()).hexdigest(), kind,
        names, stages, ("repo.read", "workspace.write", "tests.run"), ("preview.inspect",),
    )
