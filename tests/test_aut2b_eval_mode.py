"""Non-thinking evaluation payload for the Qwen3.5 structural probes."""

from mio.autonomy_eval import probe_payload


def test_qwen35_non_thinking_is_top_level():
    payload = probe_payload("qwen3.5:9b", "Reply OK", 210)
    assert payload["think"] is False
    assert "think" not in payload["options"]
    assert payload["options"]["num_predict"] == 210
    assert payload["stream"] is False


def test_other_models_keep_their_baseline_default():
    for name in ("gpt-oss:20b", "qwen3.8:27b"):
        payload = probe_payload(name, "Test", 220)
        assert "think" not in payload
        assert payload["model"] == name
        assert payload["messages"][0]["content"] == "Test"


def test_probe_payload_never_adds_external_host_or_tools():
    payload = probe_payload("qwen3.5:9b", "Evidence [R1]", 180)
    assert set(payload) == {"model", "stream", "messages", "options", "think"}
    assert "url" not in payload and "tools" not in payload
