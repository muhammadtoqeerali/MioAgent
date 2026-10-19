"""v0.4D local fleet tests: actual selection, fallback, activation and privacy."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from mio.config import Settings
from mio.llm import Completion, ModelRouter, ModelUnavailable
from mio.model_fleet import (
    FleetError,
    FleetRouter,
    check_model_id,
    default_roles,
    inventory,
    load_policy,
    parse_policy,
    report_sha256,
    score_probe,
    write_private,
)
from scripts import model_fleet as cli

D1 = "a" * 64
D2 = "b" * 64


@pytest.fixture(autouse=True)
def isolate_fleet_lock(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    root.mkdir(mode=0o700)
    monkeypatch.setattr("mio.model_fleet.policy_path", lambda: root / "model-fleet.json")


def policy(names=("gpt-oss:20b", "qwen3.8:27b")):
    return parse_policy({"schema": 1, "enabled": True,
                         "roles": default_roles(list(names)),
                         "installed_fingerprints": {name: digest for name, digest in zip(names, (D1, D2), strict=False)},
                         "benchmark_sha256": "c" * 64,
                         "cloud_allowed": False, "parallel_models": False})


def settings():
    return Settings(_env_file=None, mio_api_token="x" * 44,
                    mio_local_model="gpt-oss:20b", mio_allow_cloud=True,
                    mio_cloud_model="proprietary", mio_cloud_api_key="not-to-use",
                    mio_local_base_url="http://127.0.0.1:11434/v1", mio_model_route="auto")


def installed():
    return {"gpt-oss:20b": {"digest": D1}, "qwen3.8:27b": {"digest": D2}}


@pytest.mark.parametrize("name", ["http://evil.test", "bad model", "foo:bar-cloud", "../secret", "", "x" * 160])
def test_reject_model_id(name):
    with pytest.raises(FleetError):
        check_model_id(name)


def test_exact_policy_local_only():
    parsed = policy()
    assert parsed.roles["coding"] == ("gpt-oss:20b", "qwen3.8:27b")
    assert parsed.to_dict()["cloud_allowed"] is False


@pytest.mark.parametrize("tamper", ["cloud_allowed", "parallel_models", "fingerprint", "roles", "schema"])
def test_refuse_policy_downgrade(tamper):
    value = policy().to_dict()
    if tamper == "cloud_allowed":
        value["cloud_allowed"] = True
    elif tamper == "parallel_models":
        value["parallel_models"] = True
    elif tamper == "fingerprint":
        value["installed_fingerprints"]["gpt-oss:20b"] = "abc"
    elif tamper == "roles":
        value["roles"]["chat"] = []
    else:
        value["schema"] = 2
    with pytest.raises(FleetError):
        parse_policy(value)


def test_fleet_never_cloud_even_if_global_settings_allow_it(monkeypatch):
    calls = []

    async def fake(self, messages, max_tokens=768):
        calls.append((self.settings.mio_local_model, self.settings.mio_allow_cloud,
                      self.settings.mio_model_route))
        return Completion("ok", "local", self.settings.mio_local_model)

    monkeypatch.setattr(ModelRouter, "complete", fake)
    router = FleetRouter(settings(), "coding", policy(), installed())
    result = asyncio.run(router.complete([{"role": "user", "content": "hello"}]))
    assert result.model == "gpt-oss:20b"
    assert calls == [("gpt-oss:20b", False, "local")]


def test_fleet_switches_after_transport_error(monkeypatch):
    called = []

    async def fake(self, messages, max_tokens=768):
        called.append(self.settings.mio_local_model)
        if self.settings.mio_local_model == "gpt-oss:20b":
            raise ModelUnavailable("local HTTP 503")
        return Completion("fixed", "local", self.settings.mio_local_model)

    monkeypatch.setattr(ModelRouter, "complete", fake)
    router = FleetRouter(settings(), "coding", policy(), installed())
    output = asyncio.run(router.complete([{"role": "user", "content": "fix"}]))
    assert output.model == "qwen3.8:27b"
    assert called == ["gpt-oss:20b", "qwen3.8:27b"]
    assert router.position == 1
    assert [x.success for x in router.events] == [False, True]


def test_fleet_exhaustion_is_bounded(monkeypatch):
    called = []

    async def failing(self, messages, max_tokens=768):
        called.append(self.settings.mio_local_model)
        raise ModelUnavailable("failure")

    monkeypatch.setattr(ModelRouter, "complete", failing)
    router = FleetRouter(settings(), "repair", policy(), installed())
    with pytest.raises(ModelUnavailable):
        asyncio.run(router.complete([{"role": "user", "content": "test"}]))
    assert len(called) == 2


def test_fleet_digest_change_fails_closed_before_inference(monkeypatch):
    async def no_call(self, messages, max_tokens=768):
        raise AssertionError("model call forbidden")

    monkeypatch.setattr(ModelRouter, "complete", no_call)
    router = FleetRouter(settings(), "chat", policy(), {"gpt-oss:20b": {"digest": D2},
                                                        "qwen3.8:27b": {"digest": D2}})
    with pytest.raises(FleetError, match="digest changed"):
        asyncio.run(router.complete([]))


def test_explicit_validation_failure_advances_to_next_model(monkeypatch):
    router = FleetRouter(settings(), "coding", policy(), installed())
    assert router.advance()
    assert not router.advance()
    assert router.position == 1


def test_private_policy_round_trip_and_permissions(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    dest = private / "fleet.json"
    write_private(dest, policy().to_dict())
    assert dest.stat().st_mode & 0o077 == 0
    assert load_policy(dest) == policy()
    with pytest.raises(FleetError, match="overwrite"):
        write_private(dest, policy().to_dict())


def test_world_readable_policy_and_symlink_rejected(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    dest = private / "fleet.json"
    write_private(dest, policy().to_dict())
    dest.chmod(0o644)
    with pytest.raises(FleetError, match="private"):
        load_policy(dest)
    dest.chmod(0o600)
    link = private / "link.json"
    link.symlink_to(dest)
    with pytest.raises(FleetError, match="symlinks"):
        load_policy(link)


def test_installed_inventory_is_loopback_only_and_validates_digest():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"models": [
        {"name": "gpt-oss:20b", "digest": D1, "size": 123},
        {"name": "qwen3.8:27b", "digest": D2, "size": 456},
    ]}))
    async def test():
        async with httpx.AsyncClient(transport=transport) as client:
            return await inventory(client)
    names = asyncio.run(test())
    assert names["gpt-oss:20b"]["size_bytes"] == 123
    assert names["qwen3.8:27b"]["digest"] == D2


def test_invalid_remote_inventory_record_rejected():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"models": [
        {"name": "gpt-oss:20b", "digest": "bad"},
    ]}))
    async def test():
        async with httpx.AsyncClient(transport=transport) as client:
            return await inventory(client)
    with pytest.raises(FleetError):
        asyncio.run(test())


@pytest.mark.parametrize("role,text,expected", [
    ("coding", "def add(a,b):\n    return a + b\n", 1),
    ("coding", "I cannot write code", 0),
    ("writing", "Subject: Thursday meeting\nMeet on Thursday", 1),
    ("research", "Evidence [R1] and limitation [R2]", 1),
    ("research", "Evidence [R1] [R3]", 0),
    ("planning", '{"steps":["one","two","three"]}', 1),
    ("planning", '{"steps":["one"]}', 0),
])
def test_probe_checks(role, text, expected):
    assert score_probe(role, text)["score"] == expected


def test_report_digest_is_order_independent():
    assert report_sha256({"x": 1, "y": 2}) == report_sha256({"y": 2, "x": 1})


def test_activation_requires_original_weight_digest(tmp_path, monkeypatch):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    report_root = private / "model-benchmarks"
    report_root.mkdir(mode=0o700)
    report = {"schema": 1, "purpose": "limited-format-probes-not-general-model-quality",
              "models": {"gpt-oss:20b": D1}, "cloud_calls": False, "parallel_models": False,
              "probes": [{"model": "gpt-oss:20b", "role": role, "score": 1, "latency_s": 1.2}
                         for role in ("coding", "planning", "writing", "research")],
              "created_unix": 1}
    report["content_sha256"] = report_sha256(report)
    path = report_root / "trial.json"
    write_private(path, report)
    monkeypatch.setattr(cli, "_report_dir", lambda: report_root)
    monkeypatch.setattr(cli, "policy_path", lambda: private / "model-fleet.json")
    monkeypatch.setattr(cli, "inventory", AsyncMock(return_value={"gpt-oss:20b": {"digest": D2}}))
    with pytest.raises(FleetError, match="changed"):
        asyncio.run(cli.do_activate(path, ["gpt-oss:20b"]))
    assert not (private / "model-fleet.json").exists()
    monkeypatch.setattr(cli, "inventory", AsyncMock(return_value={"gpt-oss:20b": {"digest": D1}}))
    asyncio.run(cli.do_activate(path, [], auto=True))
    assert (private / "model-fleet.json").is_file()
    assert parse_policy(json.loads((private / "model-fleet.json").read_text())).roles["repair"] == ("gpt-oss:20b",)


def test_no_policy_uses_existing_router(monkeypatch):
    async def success(self, messages, max_tokens=768):
        return Completion("ok", "local", "gpt-oss:20b")
    monkeypatch.setattr(ModelRouter, "complete", success)
    assert asyncio.run(FleetRouter(settings(), "coding", None).complete([])).model == "gpt-oss:20b"


def test_project_generator_advances_after_invalid_model_draft(monkeypatch):
    """Actual project-drafting function uses a second local candidate on format failure."""
    from mio.project_tasks import generate_validated_draft

    calls = []

    async def fake(self, messages, max_tokens=768):
        calls.append(self.settings.mio_local_model)
        if self.settings.mio_local_model == "gpt-oss:20b":
            return Completion('{"plan": ["write implementation"], "files": []}',
                              "local", self.settings.mio_local_model)
        return Completion(json.dumps({"plan": ["implement addition"], "files": [
            {"path": "math_ops.py", "content": "def add(a, b):\n    return a + b\n"}]}),
                          "local", self.settings.mio_local_model)

    monkeypatch.setattr(ModelRouter, "complete", fake)
    router = FleetRouter(settings(), "coding", policy(), installed())
    result, completion, attempts = asyncio.run(generate_validated_draft(router, "Create math_ops.py"))
    assert attempts == 2
    assert result["files"][0]["path"] == "math_ops.py"
    assert completion.model == "qwen3.8:27b"
    assert calls == ["gpt-oss:20b", "qwen3.8:27b"]


def test_local_planner_prefers_activated_role_model(monkeypatch):
    """The existing full goal planner can use a different approved model."""
    from mio.engineering_engine import parse_goal
    from scripts.engineer_project import local_plan

    goal_data = json.loads((Path(__file__).parents[1] / "docs/examples/v04a_multiply_goal.json").read_text())
    goal = parse_goal(json.dumps(goal_data))
    roles = default_roles(["gpt-oss:20b", "qwen3.8:27b"])
    roles["planning"] = ["qwen3.8:27b", "gpt-oss:20b"]
    roles["coding"] = ["qwen3.8:27b", "gpt-oss:20b"]
    fleet = parse_policy({"schema": 1, "enabled": True, "roles": roles,
                          "installed_fingerprints": {"gpt-oss:20b": D1, "qwen3.8:27b": D2},
                          "benchmark_sha256": "c" * 64,
                          "cloud_allowed": False, "parallel_models": False})
    from scripts import engineer_project as engineer
    monkeypatch.setattr(engineer, "load_policy", lambda: fleet)
    monkeypatch.setattr(engineer, "load_model_config", lambda: {"MIO_LOCAL_MODEL": "gpt-oss:20b"})
    monkeypatch.setattr(engineer, "get_token", lambda: "s" * 44)
    monkeypatch.setattr("mio.model_fleet.inventory", AsyncMock(return_value=installed()))

    answer = json.dumps({"tasks": [
        {"role": "planning", "action": "Plan the math API behavior", "criteria": ["C1"]},
        {"role": "coding", "action": "Implement math API multiplication", "criteria": ["C1", "C2", "C3"]},
        {"role": "review", "action": "Verify the three acceptance checks", "criteria": ["C1", "C2", "C3"]},
    ]})

    async def fake(self, messages, max_tokens=768):
        return Completion(answer, "local", self.settings.mio_local_model)
    monkeypatch.setattr(ModelRouter, "complete", fake)

    planned, model = asyncio.run(local_plan(goal))
    assert model == "qwen3.8:27b"
    assert planned["tasks"][0]["model"] == "qwen3.8:27b"
    assert planned["tasks"][1]["model"] == "qwen3.8:27b"
    assert planned["criteria_mapped"] == ["C1", "C2", "C3"]


def test_disable_archives_without_rewriting_secret(tmp_path, monkeypatch):
    private = tmp_path / "runtime"
    path = private / "model-fleet.json"
    write_private(path, policy().to_dict())
    monkeypatch.setattr(cli, "policy_path", lambda: path)
    cli.do_disable()
    assert not path.exists()
    archived = private / "model-fleet.disabled.json"
    assert archived.exists() and archived.stat().st_mode & 0o077 == 0


def test_cross_model_review_and_refine_three_calls(tmp_path, monkeypatch, capsys):
    """Writing/research collaboration is real sequential routing, not a model registry."""
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Write a thoughtful research summary with honest limitations", encoding="utf-8")
    approve = policy()
    calls = []

    class FakeRouter:
        def __init__(self, settings, role, active, found=None):
            assert active is approve
            self.role = role
            self.position = 0
            self.events = []

        async def complete(self, messages, max_tokens=768):
            calls.append((self.role, self.position))
            if self.role == "review":
                return Completion("The claim lacks supporting citations.", "local", "qwen3.8:27b")
            if len(calls) == 3:
                return Completion("Revised: available evidence is insufficient.", "local", "gpt-oss:20b")
            return Completion("Preliminary analysis with limitations.", "local", "gpt-oss:20b")

    monkeypatch.setattr(cli, "load_policy", lambda: approve)
    monkeypatch.setattr(cli, "FleetRouter", FakeRouter)
    monkeypatch.setattr(cli, "_settings", lambda: settings())
    monkeypatch.setattr(cli, "inventory", AsyncMock(return_value=installed()))
    asyncio.run(cli.do_ask("research", prompt, True, None, True))
    out = capsys.readouterr().out
    assert "independent_review" in out and "refined_answer" in out
    assert "evidence is insufficient" in out
    assert calls == [("research", 0), ("review", 1), ("research", 0)]


def test_refine_without_distinct_reviewer_refused(tmp_path, monkeypatch, capsys):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Explain a design change", encoding="utf-8")
    approve = policy(("gpt-oss:20b",))

    class FakeRouter:
        def __init__(self, *_args, **_kwargs):
            self.position = 0
            self.events = []

        async def complete(self, messages, max_tokens=768):
            return Completion("Draft", "local", "gpt-oss:20b")

    monkeypatch.setattr(cli, "load_policy", lambda: approve)
    monkeypatch.setattr(cli, "FleetRouter", FakeRouter)
    monkeypatch.setattr(cli, "_settings", lambda: settings())
    monkeypatch.setattr(cli, "inventory", AsyncMock(return_value={"gpt-oss:20b": {"digest": D1}}))
    asyncio.run(cli.do_ask("writing", prompt, True, None, True))
    assert "INDEPENDENT REVIEW UNAVAILABLE" in capsys.readouterr().out


def test_refine_requires_review(tmp_path):
    with pytest.raises(FleetError, match="requires --review"):
        asyncio.run(cli.do_ask("writing", tmp_path / "missing.txt", False, None, True))
