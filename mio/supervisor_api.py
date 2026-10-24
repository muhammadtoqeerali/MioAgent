"""Authenticated owner interface for durable Scorpio supervisor plans."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from mio.supervisor_core import (
    approve_plan,
    create_plan,
    list_plans,
    pause_plan,
    read_plan,
)
from mio.work_core import RUNTIME, WorkStop


class SupervisorDraft(BaseModel):
    project_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    goal: str = Field(min_length=10, max_length=1800)
    steps: list[str] = Field(min_length=1, max_length=6)


class OwnerApproval(BaseModel):
    approved: Literal[True]


def register_supervisor_routes(app: FastAPI, require_token: Callable,
                               root: Path = RUNTIME / "work") -> None:
    auth = [Depends(require_token)]

    def safe(action: Callable, *args):
        try:
            return action(root, *args)
        except WorkStop as exc:
            raise HTTPException(409, detail=str(exc)[:240]) from exc

    @app.get("/api/supervisor/plans", dependencies=auth)
    def all_plans():
        return safe(list_plans)

    @app.post("/api/supervisor/plans", dependencies=auth, status_code=201)
    def draft(payload: SupervisorDraft):
        return safe(create_plan, payload.project_id, payload.goal, payload.steps)

    @app.get("/api/supervisor/plans/{plan_id}", dependencies=auth)
    def detail(plan_id: str):
        return safe(read_plan, plan_id)

    @app.post("/api/supervisor/plans/{plan_id}/approve", dependencies=auth)
    def approve(plan_id: str, payload: OwnerApproval):
        return safe(approve_plan, plan_id)

    @app.post("/api/supervisor/plans/{plan_id}/pause", dependencies=auth)
    def pause(plan_id: str):
        return safe(pause_plan, plan_id)
