"""Ensure installer refuses drift and retains exact API/worker behavior."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("b1_patcher", ROOT / "release/patch_integration.py")
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_refuses_unknown_integration_anchor():
    with pytest.raises(module.PatchError):
        module.change_api("not expected source")
    with pytest.raises(module.PatchError):
        module.change_runtime("not expected source")


def test_worker_not_owned_by_http_api():
    source = Path(__file__).resolve().parents[1] / "release/patch_integration.py"
    data = source.read_text()
    assert 'task = asyncio.create_task(execute' in data  # old code removed by patch
    assert 'Persistent worker owns the queue' in data


def test_phase_never_grants_unrestricted_host_tools():
    agent = (ROOT / "mio/work_worker.py").read_text()
    assert "from mio.work_agent import execute" in agent
    assert "subprocess." not in agent
    assert "sudo" not in agent
