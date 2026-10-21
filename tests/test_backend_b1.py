"""Backend B1 logic: isolation, bounded history, worker recovery, unmanaged PID guards."""
from __future__ import annotations

from pathlib import Path

from mio.project_context import MAX_HISTORY_CHARS, conversation_history
from mio.work_core import create_project, create_run, run_info, update
from mio.work_worker import pending, reconcile


def base(tmp_path: Path) -> Path:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    return private / "work"


def test_history_single_project_bounded_and_chronological(tmp_path):
    root = base(tmp_path)
    one = create_project(root, "Project conversation", "Keep explanations concise")
    other = create_project(root, "Other project", "Private instructions")
    for i in range(7):
        task = create_run(root, one["id"], f"User question number {i}")
        update(root, task["id"], "answered", mode="chat", result=f"Answer number {i}: " + "a" * 800)
    candidate = create_run(root, one["id"], "Follow up on the last five turns")
    history = conversation_history(root, one["id"], candidate["id"])
    assert len(history) <= MAX_HISTORY_CHARS
    assert "question number 6" in history
    assert "question number 0" not in history
    assert "Follow up on the last" not in history
    assert conversation_history(root, other["id"], candidate["id"]) == ""


def test_delegated_work_never_inherits_previous_goal(tmp_path):
    root = base(tmp_path)
    project = create_project(root, "Work · Task A", "Private goal")
    first = create_run(root, project["id"], "Summarize evidence")
    update(root, first["id"], "answered", result="Private answer")
    second = create_run(root, project["id"], "Another distinct goal")
    assert conversation_history(root, project["id"], second["id"]) == ""


def test_persistent_worker_preserves_queued_and_marks_abandoned(tmp_path):
    root = base(tmp_path)
    project = create_project(root, "Task project", "")
    first = create_run(root, project["id"], "First question for worker")
    assert pending(root) == first["id"]
    update(root, first["id"], "running")
    assert reconcile(root) == 1
    assert run_info(root, first["id"])["state"] == "interrupted"
    assert reconcile(root) == 0
    second = create_run(root, project["id"], "Second question for worker")
    assert pending(root) == second["id"]


def test_unknown_pid_never_treated_as_worker():
    from scripts.manage_work_worker import identified
    assert not identified(-1)
    assert not identified(1)


def test_unknown_pid_never_treated_as_image_backend():
    from scripts.manage_image_service import identified
    assert not identified(-1)
    assert not identified(1)
