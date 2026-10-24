"""Model-plan proposals are data-only, local-only and never auto-approved."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from mio.supervisor_core import advance_supervisor, list_plans
from mio.supervisor_proposal_api import register_supervisor_proposal_routes
from mio.supervisor_proposals import parse_local_proposal, propose_draft, validate_local_settings
from mio.work_core import WorkStop, create_project, db


@pytest.fixture
def work_root(tmp_path):
    parent = tmp_path / 'native'
    parent.mkdir(mode=0o700)
    return parent / 'work'


@pytest.fixture
def project(work_root):
    return create_project(work_root, 'Local planning project', 'No authority to run without owner approval')


def local_settings(**kwargs):
    return SimpleNamespace(**({'mio_local_model': 'qwen3:test', 'mio_model_route': 'local',
                              'mio_allow_cloud': False, 'mio_local_base_url': 'http://127.0.0.1:11434/v1'} | kwargs))


def test_strict_json_steps():
    assert parse_local_proposal('{"steps":["Research evidence", "Summarize findings"]}') == ['Research evidence', 'Summarize findings']


def test_json_fence_allowed_but_other_prose_rejected():
    assert len(parse_local_proposal('```json\n{"steps":["Research evidence"]}\n```')) == 1
    with pytest.raises(WorkStop):
        parse_local_proposal('Here is JSON: {"steps":["Research evidence"]}')


@pytest.mark.parametrize('bad', ['{"steps":[]}', '{"steps":["short"]}', '{"steps":["Research evidence"],"approved":true}',
                                 '{"steps":["Research evidence","Research evidence"]}',
                                 '{"steps":["Line one\\nLine two"]}', '{"steps":null}',
                                 '{"steps":'+'["Research evidence",'*6+'"Research evidence"]}'])
def test_invalid_proposals_refused(bad):
    with pytest.raises(WorkStop):
        parse_local_proposal(bad)


def test_cloud_and_missing_model_never_fallback():
    for override in ({'mio_local_model':''},{'mio_model_route':'cloud'},{'mio_allow_cloud':True},
                     {'mio_local_base_url':'https://remote.example/v1'}):
        values = {'mio_local_model': 'qwen3:test', 'mio_model_route': 'local',
                  'mio_allow_cloud': False, 'mio_local_base_url': 'http://127.0.0.1:11434/v1'}
        values.update(override)
        with pytest.raises(WorkStop):
            validate_local_settings(SimpleNamespace(**values))


def test_model_proposal_stays_draft_and_does_not_queue(monkeypatch, work_root, project):
    class FakeRouter:
        def __init__(self, settings):
            assert not settings.mio_allow_cloud
        async def complete(self, messages, max_tokens):
            assert len(messages) == 2 and max_tokens <= 1300
            return SimpleNamespace(text='{"steps":["Research peer reviewed evidence","Summarize documented limitations"]}',
                                   provider='local',model='offline-test')
    monkeypatch.setattr('mio.supervisor_proposals.ModelRouter', FakeRouter)
    result = asyncio.run(propose_draft(work_root, local_settings(), project['id'], 'Compare the available public evidence'))
    assert result['state'] == 'draft'
    assert result['provenance']['provider'] == 'local'
    assert any(e['phase']=='model.proposed' for e in result['events'])
    assert advance_supervisor(work_root) is None
    with db(work_root) as conn:
        assert conn.execute('SELECT count(*) FROM runs').fetchone()[0] == 0


def test_bad_model_reply_never_persists_plan(monkeypatch, work_root, project):
    class FakeRouter:
        def __init__(self, settings): pass
        async def complete(self, messages, max_tokens):
            return SimpleNamespace(text='{"steps":["bad"]}',provider='local',model='offline')
    monkeypatch.setattr('mio.supervisor_proposals.ModelRouter', FakeRouter)
    with pytest.raises(WorkStop):
        asyncio.run(propose_draft(work_root, local_settings(), project['id'], 'Produce a legitimate research summary'))
    assert list_plans(work_root)['plans'] == []


def test_cloud_response_rejected_even_if_settings_local(monkeypatch, work_root, project):
    class FakeRouter:
        def __init__(self, settings): pass
        async def complete(self, messages, max_tokens):
            return SimpleNamespace(text='{"steps":["Research the evidence"]}',provider='cloud',model='cloud')
    monkeypatch.setattr('mio.supervisor_proposals.ModelRouter', FakeRouter)
    with pytest.raises(WorkStop,match='Cloud'):
        asyncio.run(propose_draft(work_root, local_settings(), project['id'], 'Research valid publicly available sources'))
    assert list_plans(work_root)['plans'] == []


def test_route_enforces_existing_api_bearer(work_root):
    app = FastAPI()
    def deny():
        raise HTTPException(401, 'Unauthorized')
    register_supervisor_proposal_routes(app, local_settings(), deny, work_root)
    resp = TestClient(app).post('/api/supervisor/propose',json={'project_id':'0'*32,'goal':'Compare a scientific question'})
    assert resp.status_code == 401


def test_frontend_proposal_must_still_wait_for_owner_approval():
    root = Path(__file__).resolve().parents[1]
    # Integration patch lives in the published Supervisor page, not in this new fixture.
    page = (root/'apps/dashboard/app/supervisor/page.tsx').read_text()
    assert 'supervisor/propose' in page
    assert 'Suggest draft with local model' in page
    assert 'Approve and run' in page
