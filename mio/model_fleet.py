"""Measured, local-only model fleet for MioAgent's task roles.

Policy is owner-controlled, stored on native private Linux storage. A catalogue
entry never implies an installed model, a quality result, or an execution grant.
No cloud inference, model downloads, third-party skills or OS commands here.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from mio.config import Settings
from mio.llm import Completion, ModelRouter, ModelUnavailable

ROLES = frozenset({"chat", "planning", "coding", "repair", "review", "writing", "research"})
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,95}(?::[A-Za-z0-9._-]{1,50})?\Z")
SCHEMA = 1
BASE = "http://127.0.0.1:11434"
MAX_MODELS = 3
MAX_PROMPT_CHARS = 22_000

# Discover these from the official Ollama registry before opting into downloads.
# Size is catalogue guidance, not evidence of successful local benchmark/deployment.
CATALOGUE = {
    "gpt-oss:20b": {"family": "OpenAI gpt-oss", "purpose": "general reasoning and code", "size_class": "~14GB", "state": "known_workstation_baseline"},
    "qwen3.8:27b": {"family": "Alibaba Qwen", "purpose": "coding/research/vision candidate", "size_class": "~18GB", "state": "candidate"},
    "qwen3.5:9b": {"family": "Alibaba Qwen", "purpose": "smaller fast candidate", "size_class": "~7GB", "state": "candidate"},
    "qwen3:8b": {"family": "Alibaba Qwen", "purpose": "previously suggested candidate", "size_class": "small", "state": "candidate"},
}


class FleetError(ValueError):
    """Invalid private model policy or unsafe fleet operation."""


def check_model_id(name: str) -> str:
    if (not isinstance(name, str) or not MODEL_ID.fullmatch(name)
            or name.endswith(("-cloud", ":cloud")) or name.startswith("http") or ".." in name):
        raise FleetError("Model name is not a permitted local Ollama identifier")
    return name


def private_file(path: Path, *, allow_missing: bool = False) -> bool:
    if not path.is_absolute() or path.is_symlink() or path.parent.is_symlink():
        raise FleetError("Fleet policy path must be absolute without symlinks")
    parent = path.parent
    if not parent.is_dir():
        if allow_missing:
            return False
        raise FleetError("Fleet policy directory is missing")
    parent_stat = parent.stat()
    if parent_stat.st_uid != os.getuid() or stat.S_IMODE(parent_stat.st_mode) & 0o077:
        raise FleetError("Fleet policy parent must be user-owned and mode 0700")
    if not path.exists():
        if allow_missing:
            return False
        raise FleetError("Fleet policy file does not exist")
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > 32_768):
        raise FleetError("Fleet policy must be a private regular file under 32 KiB")
    return True


def policy_path() -> Path:
    return Path(f"/var/tmp/mioagent-native-{os.getuid()}/model-fleet.json")


@dataclass(frozen=True)
class FleetPolicy:
    roles: dict[str, tuple[str, ...]]
    installed_fingerprints: dict[str, str]
    benchmark_sha256: str
    enabled: bool = True

    def to_dict(self) -> dict:
        return {"schema": SCHEMA, "enabled": self.enabled,
                "roles": {key: list(value) for key, value in self.roles.items()},
                "installed_fingerprints": dict(self.installed_fingerprints),
                "benchmark_sha256": self.benchmark_sha256,
                "cloud_allowed": False, "parallel_models": False}


def parse_policy(data: Any) -> FleetPolicy:
    if not isinstance(data, dict) or set(data) != {
        "schema", "enabled", "roles", "installed_fingerprints", "benchmark_sha256",
        "cloud_allowed", "parallel_models",
    } or data["schema"] != SCHEMA or data["cloud_allowed"] is not False or data["parallel_models"] is not False:
        raise FleetError("Fleet policy schema or local-only guarantees are invalid")
    if data["enabled"] is not True:
        raise FleetError("Fleet policy not activated")
    if not isinstance(data["roles"], dict) or set(data["roles"]) != ROLES:
        raise FleetError("Fleet policy must define exactly seven model roles")
    roles: dict[str, tuple[str, ...]] = {}
    for role, items in data["roles"].items():
        if (not isinstance(items, list) or not 1 <= len(items) <= MAX_MODELS
                or len(items) != len(set(items))):
            raise FleetError(f"Role {role} must have 1..3 unique models")
        roles[role] = tuple(check_model_id(m) for m in items)
    fingerprints = data["installed_fingerprints"]
    if (not isinstance(fingerprints, dict) or set(fingerprints) != set().union(*roles.values())
            or any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{12,64}", v)
                   for v in fingerprints.values())):
        raise FleetError("Approved models require recorded immutable inventory digests")
    digest = data["benchmark_sha256"]
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise FleetError("A benchmark report SHA-256 is required before activation")
    return FleetPolicy(roles, fingerprints, digest)


def load_policy(path: Path | None = None) -> FleetPolicy | None:
    path = policy_path() if path is None else path
    if not private_file(path, allow_missing=True):
        return None
    return parse_policy(json.loads(path.read_text(encoding="utf-8")))


def write_private(path: Path, value: dict) -> None:
    """Atomic 0600 policy/report write; no symlinks or overwriting report artifacts."""
    private_file(path, allow_missing=True)
    if path.exists() or path.is_symlink():
        raise FleetError("Refusing to overwrite an existing fleet policy or report")
    encoded = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
    if len(encoded) > 100_000:
        raise FleetError("Fleet report exceeds 100 KiB")
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def model_digest(record: dict) -> str:
    """Use the full Ollama digest, not a mutable model name/alias."""
    digest = record.get("digest")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{12,64}", digest):
        raise FleetError("Ollama returned an invalid model digest")
    return digest


async def inventory(client: httpx.AsyncClient | None = None) -> dict[str, dict]:
    """Query installed local weights; never query remote hosts or pull models."""
    owned = client is None
    if owned:
        client = httpx.AsyncClient(timeout=12.0, trust_env=False, follow_redirects=False)
    try:
        assert client is not None
        response = await client.get(f"{BASE}/api/tags")
        response.raise_for_status()
        entries = response.json().get("models")
        if not isinstance(entries, list) or len(entries) > 200:
            raise FleetError("Ollama model inventory is invalid")
        result: dict[str, dict] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                raise FleetError("Invalid installed model record")
            # Ollama offers cloud-only tags; those must never become local candidates.
            if isinstance(entry.get("name"), str) and (
                entry["name"].endswith("-cloud") or entry["name"].endswith(":cloud")
            ):
                continue
            name = check_model_id(entry.get("name"))
            if name in result:
                raise FleetError("Duplicate installed model identifier")
            result[name] = {"digest": model_digest(entry),
                            "size_bytes": entry.get("size") if isinstance(entry.get("size"), int) else None}
        return result
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise FleetError(f"Local Ollama inventory unavailable ({type(exc).__name__})") from exc
    finally:
        if owned:
            await client.aclose()


@contextmanager
def inference_lock():
    """One active explicitly routed inference at a time (not a global Ollama lock).

    Advisory file lock is held through model fallback. Unmanaged Ollama clients
    are outside this scope and must be governed separately by the operator.
    """
    path = policy_path().with_name("model-fleet.lock")
    private_file(path, allow_missing=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise FleetError("Fleet inference lock has unsafe ownership or permissions")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise FleetError("Another routed model request is active; retry when idle") from exc
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


@dataclass
class ModelEvent:
    role: str
    model: str
    latency_s: float
    success: bool
    kind: str


class FleetRouter:
    """Local-only sequential fallback, gated on installed digest and task role.

    For project code, caller may invoke ``advance`` after trusted schema validation
    fails. On request failure, fallback is bounded to explicitly activated candidates.
    """

    def __init__(self, settings: Settings, role: str, policy: FleetPolicy | None = None,
                 installed: dict[str, dict] | None = None):
        if role not in ROLES:
            raise FleetError("Unknown task role")
        self.role = role
        self.settings = settings.model_copy(update={"mio_allow_cloud": False,
                                                    "mio_model_route": "local"})
        self.policy = load_policy() if policy is None else policy
        self.installed = installed
        self.position = 0
        self.events: list[ModelEvent] = []

    def advance(self) -> bool:
        if self.policy is None or self.position + 1 >= len(self.policy.roles[self.role]):
            return False
        self.position += 1
        return True

    async def complete(self, messages: list[dict[str, str]], max_tokens: int = 768) -> Completion:
        if self.policy is None:
            return await ModelRouter(self.settings).complete(messages, max_tokens=max_tokens)
        with inference_lock():
            return await self._complete_locked(messages, max_tokens)

    async def _complete_locked(self, messages: list[dict[str, str]], max_tokens: int) -> Completion:
        assert self.policy is not None
        installed = self.installed if self.installed is not None else await inventory()
        candidates = self.policy.roles[self.role]
        # Never silently use newer/replaced weights after operator benchmarking.
        for name in candidates:
            if name not in installed or installed[name]["digest"] != self.policy.installed_fingerprints[name]:
                raise FleetError(f"Approved model {name} was removed or its digest changed; rebenchmark")
        while self.position < len(candidates):
            name = candidates[self.position]
            config = self.settings.model_copy(update={"mio_local_model": name})
            start = time.monotonic()
            try:
                output = await ModelRouter(config).complete(messages, max_tokens=max_tokens)
                self.events.append(ModelEvent(self.role, name, round(time.monotonic() - start, 3), True, "completed"))
                if output.provider != "local" or output.model != name:
                    raise FleetError("Unexpected provider/model identity")
                return output
            except ModelUnavailable as exc:
                self.events.append(ModelEvent(self.role, name, round(time.monotonic() - start, 3), False,
                                              str(exc)[:130]))
                if not self.advance():
                    raise
        raise ModelUnavailable("All approved local models failed")


def default_roles(ordered: list[str]) -> dict[str, list[str]]:
    if not ordered or len(ordered) > MAX_MODELS:
        raise FleetError("Choose between one and three benchmarked local models")
    ordered = [check_model_id(x) for x in ordered]
    if len(set(ordered)) != len(ordered):
        raise FleetError("Duplicate candidate models")
    return {role: list(ordered) for role in sorted(ROLES)}


def score_probe(role: str, text: str) -> dict:
    """Tiny deterministic format/constraint probes; NOT an agent-quality benchmark."""
    import ast

    if role == "coding":
        try:
            tree = ast.parse(text.strip().removeprefix("```python").removesuffix("```").strip())
            funcs = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "add"]
            valid = len(funcs) == 1 and any(isinstance(x, ast.Add) for x in ast.walk(funcs[0]))
        except (SyntaxError, IndexError):
            valid = False
        return {"score": int(valid), "check": "Python AST of add(a,b); not executed"}
    if role == "writing":
        lower = text.casefold()
        return {"score": int(all(x in lower for x in ("subject", "meeting", "thursday"))),
                "check": "Contains three brief writing constraints"}
    if role == "research":
        return {"score": int("[R1]" in text and "[R2]" in text and "[R3]" not in text),
                "check": "Uses both given evidence labels without invented R3; not factual audit"}
    if role == "planning":
        try:
            data = json.loads(text.strip().removeprefix("```json").removesuffix("```").strip())
            valid = isinstance(data, dict) and isinstance(data.get("steps"), list) and len(data["steps"]) == 3
        except ValueError:
            valid = False
        return {"score": int(valid), "check": "Exactly three structured planning steps"}
    raise FleetError("No probe defined for requested role")


PROBES = {
    "planning": ("Return JSON only with key steps and exactly 3 short strings describing how to build and test a Python add(a,b) function.", 220),
    "coding": ("Return only Python source for a function named add(a,b) which returns the sum. No prose or markdown.", 210),
    "writing": ("Write a concise professional email with Subject line requesting a meeting on Thursday. Include both the words meeting and Thursday.", 210),
    "research": ("Use ONLY these supplied evidence records: [R1] a study enrolled 20 patients; [R2] the study had no control group. Summarize the evidence limitations in two sentences and cite [R1] and [R2]. Do not invent sources.", 220),
}


def report_sha256(report: dict) -> str:
    raw = json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()
