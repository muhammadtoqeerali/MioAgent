"""IMG3D1: real authenticated image-status/file recovery and private storage contracts."""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from mio.chat_lifecycle import ArchivedChat  # noqa: F401 - existing legacy schema registration
from mio.database import Base, ChatMessage, Conversation
from mio.omni_images import ImageTurn, register_omni_routes
from mio.studio_api import _jobs, _write_job
from mio.studio_files import StudioError

PNG = bytes.fromhex('89504e470d0a1a0a') + b'demo-png-bytes-for-metadata-check'
AUTH = {'Authorization': 'Bearer owner-test-token'}


def _test_env(tmp_path: Path, monkeypatch):
    from mio import omni_images as module

    private = tmp_path / 'private'
    private.mkdir(mode=0o700)
    studio = private / 'studio'
    studio.mkdir(mode=0o700)
    studio.chmod(0o755)  # Reproduce the workstation's safe public-traverse parent.
    monkeypatch.setattr(module, 'PRIVATE_IMAGE_ROOT', studio / 'omni-images')
    engine = create_engine('sqlite+pysqlite:///' + str(tmp_path / 'test.db'),
                           connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    app.state.sessions = factory

    async def submit(_payload):
        return {'id': 'b' * 32, 'state': 'queued'}

    class Payload:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    def auth(authorization: str | None = Header(default=None)):
        if authorization != AUTH['Authorization']:
            raise HTTPException(401, 'Unauthorized')

    register_omni_routes(app, auth, tmp_path, submit, Payload)
    return TestClient(app), factory, engine, module


def _store_job(root: Path, job_id: str):
    _jobs(root)
    _write_job(root, {'id': job_id, 'state': 'ready', 'backend': 'flux2',
                      'sha256': hashlib.sha256(PNG).hexdigest(), 'bytes': len(PNG),
                      'operation': 'generate'})
    output = _jobs(root) / (job_id + '.png')
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(PNG)


def test_completed_image_roundtrip_survives_repeated_status_calls(tmp_path, monkeypatch):
    client, factory, engine, module = _test_env(tmp_path, monkeypatch)
    _store_job(tmp_path, 'b' * 32)
    with factory.begin() as db:
        conversation = Conversation(title='Private image recovery')
        db.add(conversation)
        db.flush()
        cid = conversation.id
        db.add(ImageTurn(id='a'*32, scope='chat', scope_id=cid,
                         job_id='b'*32, source_turn=None, operation='create', prompt='Create portrait'))
        db.add(ChatMessage(conversation_id=cid, role='assistant', content='MIO_IMAGE_TURN:' + 'a'*32))
    assert client.get('/api/omni/images/' + 'a'*32).status_code == 401
    for _ in range(2):
        resp = client.get('/api/omni/images/' + 'a'*32, headers=AUTH)
        assert resp.status_code == 200, resp.status_code
        assert resp.json()['state'] == 'ready'
        asset = client.get('/api/omni/images/' + 'a'*32 + '/file', headers=AUTH)
        assert asset.status_code == 200 and asset.content == PNG
        assert asset.headers['content-type'].startswith('image/png')
    target = module.PRIVATE_IMAGE_ROOT / ('a'*32 + '.png')
    assert target.is_file() and stat.S_IMODE(target.stat().st_mode) == 0o600
    assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700
    listing = client.get('/api/omni/turns/chat/' + cid, headers=AUTH)
    assert listing.status_code == 200 and len(listing.json()['turns']) == 1
    with factory() as db:
        assert db.scalar(select(ChatMessage).where(ChatMessage.conversation_id == cid)) is not None
    engine.dispose()


def test_unsafe_existing_directory_maps_to_controlled_409(tmp_path, monkeypatch):
    client, factory, engine, module = _test_env(tmp_path, monkeypatch)
    _store_job(tmp_path, 'b'*32)
    with factory.begin() as db:
        convo=Conversation(title='Unsafe storage')
        db.add(convo)
        db.flush()
        db.add(ImageTurn(id='a'*32, scope='chat', scope_id=convo.id,
                         job_id='b'*32, source_turn=None, operation='create', prompt='create image'))
    image_path = module.PRIVATE_IMAGE_ROOT
    image_path.mkdir(mode=0o755)
    image_path.chmod(0o755)
    response=client.get('/api/omni/images/' + 'a'*32, headers=AUTH)
    assert response.status_code == 409
    assert response.json()['detail'] == 'Private image storage unavailable'
    assert image_path.stat().st_mode & 0o077
    engine.dispose()


def test_owner_parent_mode_0755_retains_private_leaf(tmp_path, monkeypatch):
    _client, _factory, engine, module = _test_env(tmp_path, monkeypatch)
    parent = module.PRIVATE_IMAGE_ROOT.parent
    assert stat.S_IMODE(parent.stat().st_mode) == 0o755
    image_store = module._image_store()
    assert image_store == module.PRIVATE_IMAGE_ROOT
    assert stat.S_IMODE(image_store.stat().st_mode) == 0o700
    assert stat.S_IMODE(parent.stat().st_mode) == 0o755
    engine.dispose()


def test_group_writable_image_parent_is_rejected(tmp_path, monkeypatch):
    _client, _factory, engine, module = _test_env(tmp_path, monkeypatch)
    module.PRIVATE_IMAGE_ROOT.parent.chmod(0o775)
    with pytest.raises(StudioError, match='owner-controlled'):
        module._image_store()
    assert not module.PRIVATE_IMAGE_ROOT.exists()
    engine.dispose()


def test_filename_traversal_denied(tmp_path, monkeypatch):
    _, _, engine, module = _test_env(tmp_path, monkeypatch)
    with pytest.raises(StudioError):
        module._asset_path('../../secrets')
    engine.dispose()


def test_default_storage_is_native_private_runtime_not_shared_home_mount():
    from mio import omni_images as module

    assert module.PRIVATE_IMAGE_ROOT == module.RUNTIME_ROOT / 'studio' / 'omni-images'
    assert module.PRIVATE_IMAGE_ROOT.is_relative_to(module.RUNTIME_ROOT)
    assert module.PRIVATE_IMAGE_ROOT != Path.home() / '.local/share/mioagent/omni-images'
