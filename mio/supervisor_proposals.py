"""SCORPIO9B: strictly local model suggestions; every proposal is a Work draft.

The model cannot approve, queue, execute, select a provider, or grant tools.
Owner's explicit 9A approval remains the only dispatch gate.
"""
from __future__ import annotations

import json
from pathlib import Path

from mio.config import Settings
from mio.llm import ModelRouter, ModelUnavailable, validate_provider_url
from mio.supervisor_core import _event, _schema, create_plan
from mio.work_core import WorkStop, _id, db, project_info

MAX_MODEL_TEXT = 9_000
MAX_TOTAL_STEPS_TEXT = 6_000


def parse_local_proposal(raw: str) -> list[str]:
    """Treat untrusted model output as only a bounded JSON data object."""
    if not isinstance(raw, str) or not 2 <= len(raw) <= MAX_MODEL_TEXT:
        raise WorkStop("Local proposal response exceeded permitted size")
    text = raw.strip()
    if text.startswith("```json\n") and text.endswith("\n```"):
        text = text[len("```json\n"):-len("\n```")].strip()
    try:
        obj = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise WorkStop("Local model must return a JSON object containing only steps") from exc
    if not isinstance(obj, dict) or set(obj) != {"steps"}:
        raise WorkStop("Local proposal must contain only the steps field")
    steps = obj["steps"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= 6:
        raise WorkStop("Local proposal must contain 1–6 steps")
    if any(not isinstance(step, str) or not 8 <= len(step.strip()) <= 2_500
           or "\x00" in step or "\n" in step or "\r" in step
           for step in steps):
        raise WorkStop("Local proposal contains an invalid bounded step")
    normalized = [step.strip() for step in steps]
    if sum(len(step) for step in normalized) > MAX_TOTAL_STEPS_TEXT:
        raise WorkStop("Local proposal step budget exceeded")
    if len(set(normalized)) != len(normalized):
        raise WorkStop("Local proposal contains duplicate steps")
    return normalized


def validate_local_settings(settings: Settings) -> None:
    if (not settings.mio_local_model or settings.mio_model_route != "local"
            or settings.mio_allow_cloud):
        raise WorkStop("Supervisor proposal requires explicitly configured local-only model routing")
    # Ensure a configured endpoint cannot silently redirect model prompts elsewhere.
    try:
        validate_provider_url(settings.mio_local_base_url, local=True)
    except ValueError as exc:
        raise WorkStop("Supervisor model endpoint is not approved local loopback") from exc


async def propose_draft(root: Path, settings: Settings, project_id: str, goal: str) -> dict:
    """One local model request, validated data, then durable unapproved plan."""
    project_id = _id(project_id)
    if not isinstance(goal, str) or not 10 <= len(goal.strip()) <= 1_800:
        raise WorkStop("Supervisor goal must contain 10–1800 characters")
    project_info(root, project_id)  # verify real Work project before inference
    validate_local_settings(settings)
    router = ModelRouter(settings)
    instructions = (
        "Return a JSON object with exactly one key, steps, containing 1 to 6 concise "
        "standalone task instructions. Each task must be 8–2500 characters and "
        "fit the authorized bounded Work assistant: evidence research, document analysis "
        "or written summaries. No terminal commands, filesystem modification, tool grants, "
        "network address changes, agent self-authorization, or deployment claims. "
        "Output JSON only. The owner will review and approve or reject the draft."
    )
    try:
        reply = await router.complete([
            {"role": "system", "content": instructions},
            {"role": "user", "content": "Create a short draft work plan for this goal:\n" + goal.strip()},
        ], max_tokens=1_300)
    except ModelUnavailable as exc:
        raise WorkStop("Configured local model could not generate a proposal") from exc
    if reply.provider != "local":
        raise WorkStop("Cloud or unverified proposal providers are not permitted")
    steps = parse_local_proposal(reply.text)
    # No Work tasks are queued by this operation; create_plan is draft-only.
    proposal = create_plan(root, project_id, goal, steps)
    with db(root) as conn:
        _schema(conn)
        _event(conn, proposal["id"], "model.proposed",
               "Unapproved local model proposal; owner must review every step")
    from mio.supervisor_core import read_plan
    return {**read_plan(root, proposal["id"]),
            "provenance": {"provider": "local", "model": str(reply.model)[:128]}}
