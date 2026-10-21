"""Bounded prior-turn context from a single explicitly selected Work project.

Only completed turns from the same project enter the prompt. Old answers and
uploads remain reference data; they do not expand computer/tool permissions.
"""
from __future__ import annotations

from pathlib import Path

from mio.work_core import db, project_info

MAX_HISTORY_TURNS = 5
MAX_HISTORY_CHARS = 4400


def conversation_history(root: Path, project_id: str, current_run_id: str) -> str:
    info = project_info(root, project_id)
    # Delegated Work goals have distinct acceptance contracts; do not combine
    # previous jobs into a new assignment by default.
    if info["title"].startswith("Work · "):
        return ""
    # rowid breaks same-second timestamp ties. Always filter by project IN SQL.
    with db(root) as conn:
        rows = conn.execute(
            "SELECT prompt,result FROM runs WHERE project=? AND id<>? "
            "AND state IN ('answered','needs_review') AND result IS NOT NULL "
            "ORDER BY rowid DESC LIMIT ?",
            (project_id, current_run_id, MAX_HISTORY_TURNS),
        ).fetchall()
    parts = [f"PREVIOUS USER: {r['prompt'][:450]}\n"
             f"PREVIOUS MIOAGENT: {r['result'][:850]}" for r in reversed(rows)]
    return "\n\n".join(parts)[-MAX_HISTORY_CHARS:]
