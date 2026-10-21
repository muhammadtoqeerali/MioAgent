"""B2A lifecycle regressions: real SQLite records, no service/GPU/network writes."""

from __future__ import annotations

import base64
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from mio.chat_lifecycle import ArchivedChat, list_chat_query, register_chat_lifecycle
from mio.database import AIJob, ChatMessage, Conversation, Task, create_database
from mio.studio_files import save_attachment
from mio.work_core import WorkStop, create_project, create_run, db, event, link_file, update
from mio.work_lifecycle import archive_project, delete_project, listed_projects


def test_chat_archive_restore_and_hard_delete(tmp_path: Path):
    engine, sessions = create_database(f"sqlite:///{tmp_path / 'chat.db'}")
    app = FastAPI()
    app.state.sessions = sessions
    register_chat_lifecycle(app, lambda: None)
    with sessions.begin() as db_session:
        c = Conversation(title="Remove me")
        db_session.add(c)
        db_session.flush()
        task = Task(kind="ai_chat", prompt="Hi", status="completed")
        db_session.add(task)
        db_session.flush()
        message = ChatMessage(conversation_id=c.id, role="user", content="Hi")
        db_session.add(message)
        db_session.flush()
        db_session.add(AIJob(task_id=task.id, conversation_id=c.id,
                             message_id=message.id))
        chat_id, task_id = c.id, task.id
    with TestClient(app) as client:
        assert client.post(f"/api/assistant/conversations/{chat_id}/archive").status_code == 200
        with sessions() as db_session:
            archived_chat = db_session.scalar(list_chat_query(archived=True))
            assert archived_chat is not None and archived_chat.id == chat_id
            assert list(db_session.scalars(list_chat_query())) == []
        assert client.post(f"/api/assistant/conversations/{chat_id}/restore").status_code == 200
        assert client.delete(f"/api/assistant/conversations/{chat_id}").json()["deleted"] is True
        assert client.delete(f"/api/assistant/conversations/{chat_id}").status_code == 404
    with sessions() as db_session:
        assert db_session.get(Conversation, chat_id) is None
        assert db_session.get(Task, task_id) is None
        assert db_session.scalars(select(ChatMessage)).all() == []
        assert db_session.scalars(select(AIJob)).all() == []
        assert db_session.scalars(select(ArchivedChat)).all() == []
    engine.dispose()


def test_chat_delete_blocks_active_task(tmp_path: Path):
    engine, sessions = create_database(f"sqlite:///{tmp_path / 'pending.db'}")
    app = FastAPI()
    app.state.sessions = sessions
    register_chat_lifecycle(app, lambda: None)
    with sessions.begin() as db_session:
        c = Conversation(title="Pending")
        db_session.add(c)
        db_session.flush()
        task = Task(kind="ai_chat", prompt="Hi", status="running")
        db_session.add(task)
        db_session.flush()
        message = ChatMessage(conversation_id=c.id, role="user", content="Hi")
        db_session.add(message)
        db_session.flush()
        db_session.add(AIJob(task_id=task.id, conversation_id=c.id,
                             message_id=message.id))
        chat_id = c.id
    with TestClient(app) as client:
        assert client.delete(f"/api/assistant/conversations/{chat_id}").status_code == 409
    with sessions() as db_session:
        assert db_session.get(Conversation, chat_id) is not None
    engine.dispose()


def _work_root(tmp_path):
    parent = tmp_path / "owner"
    parent.mkdir(mode=0o700)
    parent.chmod(0o700)
    return parent / "work"


def test_work_archive_restore_and_delete_all_events(tmp_path):
    root = _work_root(tmp_path)
    item = create_project(root, "Calculator research", "Owner written instructions")
    run = create_run(root, item["id"], "Explain square roots")
    event(root, run["id"], "test", "A bounded event")
    update(root, run["id"], "answered", mode="chat", result="Root is 2")
    assert archive_project(root, item["id"], archive=True)["archived"]
    assert listed_projects(root) == []
    assert len(listed_projects(root, archived=True)) == 1
    archive_project(root, item["id"], archive=False)
    assert len(listed_projects(root)) == 1
    outcome = delete_project(root, item["id"])
    assert outcome["deleted"] and outcome["runs_deleted"] == 1
    with db(root) as connection:
        for query in (
            "SELECT count(*) FROM projects", "SELECT count(*) FROM runs",
            "SELECT count(*) FROM events", "SELECT count(*) FROM assets",
            "SELECT count(*) FROM memories", "SELECT count(*) FROM project_archives",
        ):
            assert connection.execute(query).fetchone()[0] == 0


def test_work_delete_refuses_active_run(tmp_path):
    root = _work_root(tmp_path)
    item = create_project(root, "Calculator work", "Instructions")
    create_run(root, item["id"], "Build calculator")
    for action in (lambda: delete_project(root, item["id"]),
                   lambda: archive_project(root, item["id"], archive=True)):
        try:
            action()
        except WorkStop:
            pass
        else:
            raise AssertionError("An active Work run must protect the project")


def test_shared_upload_is_retained_then_deleted(tmp_path, monkeypatch):
    import mio.work_core as core
    import mio.work_lifecycle as lifecycle

    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    runtime.chmod(0o700)
    monkeypatch.setattr(core, "RUNTIME", runtime)
    monkeypatch.setattr(lifecycle, "RUNTIME", runtime)
    meta = save_attachment(runtime / "studio" / "attachments", "paper.txt",
                           base64.b64encode(b"shared knowledge").decode())
    root = _work_root(tmp_path)
    a = create_project(root, "First project", "Info")
    b = create_project(root, "Second project", "Info")
    link_file(root, a["id"], meta["id"])
    link_file(root, b["id"], meta["id"])
    retained = delete_project(root, a["id"])
    assert retained["shared_uploads_retained"] == 1
    assert (runtime / "studio" / "attachments" / (meta["id"] + ".bin")).exists()
    removed = delete_project(root, b["id"])
    assert removed["uploads_deleted"] == 1
    for suffix in (".bin", ".json"):
        assert not (runtime / "studio" / "attachments" / (meta["id"] + suffix)).exists()
