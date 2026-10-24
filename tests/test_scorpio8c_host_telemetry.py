"""SCORPIO8C offline source contracts and isolated host telemetry gates."""
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from mio import system_telemetry as t

ROOT = Path(__file__).resolve().parents[1]

def read(rel): return (ROOT/rel).read_text(encoding="utf-8")

def test_telemetry_requires_backend_auth(tmp_path):
    app=FastAPI()
    def deny(): raise HTTPException(status_code=401,detail="Unauthorized")
    t.register_system_telemetry_routes(app,deny,SimpleNamespace(mio_workspace_root=tmp_path))
    r=TestClient(app).get("/api/system/telemetry")
    assert r.status_code==401

def test_registered_only_get_no_mutation(tmp_path):
    app=FastAPI()
    t.register_system_telemetry_routes(app, lambda:None, SimpleNamespace(mio_workspace_root=tmp_path))
    routes=[r for r in app.routes if getattr(r,'path',None)=="/api/system/telemetry"]
    assert len(routes)==1 and routes[0].methods=={"GET"}

def test_cpu_percent_measured_delta(monkeypatch):
    items=iter(((1000,400),(1200,450)))
    monkeypatch.setattr(t,'_cpu_snapshot',lambda:next(items))
    monkeypatch.setattr(t.time,'sleep',lambda _x:None)
    assert t._cpu_percent()==75.0

def test_cpu_missing_sensor_never_zero(monkeypatch):
    monkeypatch.setattr(t,'_cpu_snapshot',lambda:None)
    assert t._cpu_percent() is None

def test_gpu_without_driver_is_unavailable(monkeypatch):
    monkeypatch.setattr(t.shutil,'which',lambda _:None)
    assert t._gpu_info()['state']=='unavailable'

def test_nvidia_query_bounded_and_no_shell(monkeypatch):
    monkeypatch.setattr(t.shutil,'which',lambda _: '/bin/true')
    def fake_run(argv,**kwargs):
        assert argv[0]=='/bin/true' and argv[1].startswith('--query-gpu=')
        assert kwargs['stdin'] is not None and kwargs['timeout']<=2
        assert kwargs['check'] is False and 'shell' not in kwargs
        return SimpleNamespace(returncode=0,stdout='0, NVIDIA A100, 33, 2048, 8192\n')
    monkeypatch.setattr(t.subprocess,'run',fake_run)
    data=t._gpu_info()
    assert data['state']=='measured'
    assert data['devices'][0]['memory_percent']==25.0

def test_disk_space_reads_fixed_directory(tmp_path):
    data=t._disk('Workspace',tmp_path)
    assert data['total_bytes']>0 and data['free_bytes']>=0
    assert data['used_percent'] is not None

def test_frontend_has_no_fake_host_numbers():
    code=read('apps/dashboard/app/_mio/scorpio8c-resources.tsx')
    assert 'mioApi<Snapshot>("system/telemetry")' in code
    assert 'Measurement' not in code or 'API host' in code
    assert 'No readings are assumed' in code
    assert 'setInterval' in code and '12000' in code
    assert 'remote' in code.lower()

def test_brand_and_two_page_integration():
    from xml.etree import ElementTree
    logo=read('apps/dashboard/public/scorpio-mark.svg')
    tree=ElementTree.fromstring(logo)
    assert tree.attrib['viewBox']=='0 0 128 128'
    assert 'feGaussianBlur' in logo and 'linearGradient' in logo
    shell=read('apps/dashboard/app/_mio/scorpio8a-shell.tsx')
    assert '<ScorpioResources/>' in shell
    assert 'path === "/control-room" || path === "/system-health"' in shell
    assert 'scorpio8c.css' in read('apps/dashboard/app/layout.tsx')
    assert 'register_system_telemetry_routes(app, require_token, settings)' in read('mio/api.py')
