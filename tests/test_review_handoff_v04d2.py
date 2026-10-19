"""v0.4D.2 regression for local Qwen independent final-answer review."""

import asyncio
import json

import httpx
import pytest

from mio.config import Settings
from mio.llm import Completion, ModelRouter, ModelUnavailable
from mio.model_fleet import FleetRouter, parse_policy


def settings(model="qwen3.8:27b", *, cloud=False):
    return Settings(_env_file=None, mio_api_token="x" * 44,
                    mio_local_model=model, mio_model_route="local",
                    mio_local_base_url="http://127.0.0.1:11434/v1",
                    mio_allow_cloud=cloud)


def fake_transport(monkeypatch, callback):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(callback)
    monkeypatch.setattr("mio.llm.httpx.AsyncClient", lambda **opts: original(
        transport=transport, timeout=opts.get("timeout"), trust_env=False,
        follow_redirects=False))


def test_native_review_requests_final_only_and_never_returns_thinking(monkeypatch):
    observed = []

    def handle(request):
        observed.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, json={
            "message": {"content": "Unverified trial claims must be removed.",
                        "thinking": "private intermediate text"},
            "prompt_eval_count": 29, "eval_count": 12})

    fake_transport(monkeypatch, handle)
    reply = asyncio.run(ModelRouter(settings()).complete_no_think([
        {"role": "user", "content": "Review this draft."}], 1600))
    assert reply.text == "Unverified trial claims must be removed."
    assert "private intermediate" not in reply.text
    assert reply.output_tokens == 12
    assert observed[0][0] == "http://127.0.0.1:11434/api/chat"
    payload = observed[0][1]
    assert payload["model"] == "qwen3.8:27b"
    assert payload["think"] is False
    assert payload["stream"] is False
    assert payload["options"]["num_predict"] == 1600


def test_cloud_and_non_qwen_never_use_native_review(monkeypatch):
    def no_network(_request):
        raise AssertionError("network forbidden")

    fake_transport(monkeypatch, no_network)
    for config in (settings("gpt-oss:20b"), settings(cloud=True)):
        with pytest.raises(ModelUnavailable, match="approved local Qwen3"):
            asyncio.run(ModelRouter(config).complete_no_think([], 1600))


def test_upstream_rejection_does_not_expose_response_body(monkeypatch):
    fake_transport(monkeypatch, lambda _request: httpx.Response(
        400, json={"error": "some private prompt text"}))
    with pytest.raises(ModelUnavailable, match="HTTP 400") as captured:
        asyncio.run(ModelRouter(settings()).complete_no_think([], 1600))
    assert "private prompt" not in str(captured.value)


def test_no_final_answer_cannot_be_replaced_by_thinking(monkeypatch):
    fake_transport(monkeypatch, lambda _request: httpx.Response(200, json={
        "message": {"content": "", "thinking": "Do not display reasoning"}}))
    with pytest.raises(ModelUnavailable, match="invalid final response"):
        asyncio.run(ModelRouter(settings()).complete_no_think([], 1600))


def test_fleet_review_uses_native_only_when_opted_in(monkeypatch, tmp_path):
    path = tmp_path / "model-fleet.json"
    monkeypatch.setattr("mio.model_fleet.policy_path", lambda: path)
    names = ["gpt-oss:20b", "qwen3.8:27b"]
    p = parse_policy({"schema": 1, "enabled": True,
                      "roles": {r: names for r in (
                          "chat", "planning", "coding", "repair", "review", "writing", "research")},
                      "installed_fingerprints": {names[0]: "a" * 64, names[1]: "b" * 64},
                      "benchmark_sha256": "c" * 64,
                      "cloud_allowed": False, "parallel_models": False})
    installed = {names[0]: {"digest": "a" * 64}, names[1]: {"digest": "b" * 64}}
    calls = []

    async def native(self, messages, max_tokens=768):
        calls.append(("native", self.settings.mio_local_model))
        return Completion("Review completed", "local", self.settings.mio_local_model)

    async def compatible(self, messages, max_tokens=768):
        calls.append(("compatible", self.settings.mio_local_model))
        return Completion("Draft completed", "local", self.settings.mio_local_model)

    monkeypatch.setattr(ModelRouter, "complete_no_think", native)
    monkeypatch.setattr(ModelRouter, "complete", compatible)
    reviewed = FleetRouter(settings("gpt-oss:20b"), "review", p, installed)
    reviewed.position = 1
    reviewed.prefer_direct_answer = True
    result = asyncio.run(reviewed.complete([{"role": "user", "content": "review"}], 1800))
    assert result.model == "qwen3.8:27b"
    assert calls == [("native", "qwen3.8:27b")]
    drafted = FleetRouter(settings("gpt-oss:20b"), "coding", p, installed)
    asyncio.run(drafted.complete([{"role": "user", "content": "code"}], 1800))
    assert calls[-1] == ("compatible", "gpt-oss:20b")


def test_fleet_unit_tests_never_read_live_operator_policy():
    """An activated real fleet must not hijack mock-model API tests."""
    from mio.model_fleet import load_policy, policy_path

    assert "isolated-fleet" in str(policy_path())
    assert load_policy() is None
