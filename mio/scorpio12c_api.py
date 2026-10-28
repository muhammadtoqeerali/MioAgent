"""Authenticated S12C offline coding workspace endpoints (no model/tool grants)."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from mio.scorpio12c_core import (
    STORE,
    CodingStop,
    cancel_job,
    create_job,
    execute_job,
    list_jobs,
    read_job,
    status,
)


class NewRehearsal(BaseModel):
    case_name: Literal["arithmetic", "normalization", "intervals"]
    approved: Literal[True]


class Approval(BaseModel):
    approved: Literal[True]


def register_scorpio12c_routes(app: FastAPI, require_token: Callable,
                                root: Path = STORE) -> None:
    auth = [Depends(require_token)]

    def safe(action: Callable, *args):
        try:
            return action(*args, root=root)
        except (CodingStop, OSError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)[:200]) from exc

    @app.get("/api/scorpio/coding/status", dependencies=auth)
    def get_status():
        return status()

    @app.get("/api/scorpio/coding/jobs", dependencies=auth)
    def get_jobs():
        return safe(list_jobs)

    @app.post("/api/scorpio/coding/jobs", dependencies=auth, status_code=201)
    def new_job(payload: NewRehearsal):
        return safe(create_job, payload.case_name)

    @app.get("/api/scorpio/coding/jobs/{job_id}", dependencies=auth)
    def get_job(job_id: str):
        return safe(read_job, job_id)

    @app.post("/api/scorpio/coding/jobs/{job_id}/execute", dependencies=auth)
    def start_job(job_id: str, payload: Approval):
        return safe(execute_job, job_id)

    @app.post("/api/scorpio/coding/jobs/{job_id}/cancel", dependencies=auth)
    def stop_job(job_id: str, payload: Approval):
        return safe(cancel_job, job_id)
