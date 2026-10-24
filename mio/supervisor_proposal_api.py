"""Owner-authenticated, non-executing endpoint for local-model plan suggestions."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from mio.config import Settings
from mio.supervisor_proposals import propose_draft
from mio.work_core import RUNTIME, WorkStop


class ProposedGoal(BaseModel):
    project_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    goal: str = Field(min_length=10, max_length=1800)


def register_supervisor_proposal_routes(
    app: FastAPI, settings: Settings, require_token: Callable,
    root: Path = RUNTIME / "work",
) -> None:
    @app.post("/api/supervisor/propose", dependencies=[Depends(require_token)], status_code=201)
    async def local_proposal(payload: ProposedGoal):
        try:
            return await propose_draft(root, settings, payload.project_id, payload.goal)
        except WorkStop as exc:
            raise HTTPException(status_code=409, detail=str(exc)[:200]) from exc
