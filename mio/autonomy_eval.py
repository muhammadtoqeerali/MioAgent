"""Repeatable, local-only LLM smoke evaluations; not a frontier-model benchmark.

Never installs or changes models or role policies. Compare the same prompts with
fixed scoring, record latency and immutable local model inventory digests.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import time
from pathlib import Path

import httpx

from mio.autonomy_program import path_for
from mio.model_fleet import inference_lock, inventory, score_probe

PROBES = {
    "planning": ("Return JSON only with key steps and exactly 3 short strings describing how to build and test a Python add(a,b) function.", 220),
    "coding": ("Return only Python source for a function named add(a,b) which returns the sum. No prose or markdown.", 210),
    "writing": ("Write a concise professional email with Subject line requesting a meeting on Thursday. Include both the words meeting and Thursday.", 210),
    "research": ("Use ONLY these supplied evidence records: [R1] a study enrolled 20 patients; [R2] the study had no control group. Summarize the evidence limitations in two sentences and cite [R1] and [R2]. Do not invent sources.", 220),
}
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
HOST = "http://127.0.0.1:11434"


def allowed_models(models: list[str], installed: dict) -> list[str]:
    if not 1 <= len(models) <= 3 or len(set(models)) != len(models):
        raise ValueError("Select one to three distinct installed models")
    for name in models:
        if not isinstance(name, str) or not NAME.fullmatch(name) or name not in installed:
            raise ValueError("Unknown or invalid local model")
        if name.endswith((":cloud", "-cloud")):
            raise ValueError("Remote-model identifiers are forbidden")
    return models


def grade(role: str, response: str) -> dict:
    if role not in PROBES:
        raise ValueError("Unknown evaluation role")
    # Code format and citations are structural checks, not broad intelligence metrics.
    return score_probe(role, response)


def probe_payload(name: str, prompt: str, max_tokens: int) -> dict:
    """Small format probes disable reasoning for Qwen3.5 so final answers are scored."""
    payload = {
        "model": name,
        "stream": False,
        "messages": [{"role": "user", "content": prompt}],
        "options": {"temperature": 0, "num_predict": max_tokens},
    }
    if name == "qwen3.5:9b":
        payload["think"] = False
    return payload


async def evaluate(models: list[str], *, timeout_s: float = 110.0) -> dict:
    if not 20.0 <= timeout_s <= 240.0:
        raise ValueError("Benchmark timeout outside approved range")
    installed = await inventory()
    names = allowed_models(models, installed)
    results: list[dict] = []
    # Use the existing fleet lock so image and other fleet-controlled tasks
    # do not unexpectedly share a GPU with these sequential probes.
    with inference_lock():
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False,
                                     timeout=httpx.Timeout(timeout_s, connect=6.0)) as client:
            for name in names:
                for role, (prompt, max_tokens) in PROBES.items():
                    start = time.monotonic()
                    item = {"model": name, "role": role, "passed": False,
                            "latency_s": 0.0, "failure": None, "score": 0}
                    try:
                        response = await client.post(
                            f"{HOST}/api/chat",
                            json=probe_payload(name, prompt, max_tokens),
                        )
                        response.raise_for_status()
                        value = response.json().get("message", {}).get("content")
                        if not isinstance(value, str) or not value.strip():
                            raise ValueError("Empty or invalid model response")
                        check = grade(role, value)
                        item["passed"] = bool(check["score"])
                        item["score"] = check["score"]
                        item["criterion"] = check["check"]
                    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                        item["failure"] = type(exc).__name__
                    item["latency_s"] = round(time.monotonic() - start, 3)
                    results.append(item)
    report = {"schema": 1, "meaning": "tiny_local_format_probes_not_sota_quality",
              "run_at": int(time.time()),
              "models": [{"name": x, "digest": installed[x]["digest"]} for x in names],
              "results": results, "cloud_calls": False, "model_downloads": False,
              "role_policy_modified": False}
    return report


def write_report(report: dict, store: Path | None = None) -> Path:
    store = path_for() if store is None else store
    # The backlog initialization must create/secure this folder first.
    info = store.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError("Private runtime autonomy folder unavailable")
    reports = store / "reports"
    if not reports.exists():
        reports.mkdir(mode=0o700)
    st = reports.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise RuntimeError("Insecure report directory")
    raw = (json.dumps(report, sort_keys=True, indent=2) + "\n").encode()
    if len(raw) > 75_000:
        raise RuntimeError("Benchmark report exceeds byte budget")
    digest = hashlib.sha256(raw).hexdigest()
    target = reports / (digest + ".json")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return target
