"""Authenticated, read-only Scorpio9C grant and vetted tool inventory API."""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException

from mio.scorpio9c_observe import grant_inventory, tool_catalog
from mio.work_core import RUNTIME, WorkStop


def register_scorpio9c_observe_routes(app: FastAPI, require_token: Callable,
                                      root: Path = RUNTIME / "work") -> None:
    auth = [Depends(require_token)]

    @app.get("/api/tools/registry", dependencies=auth)
    def tools_registry():
        return tool_catalog()

    @app.get("/api/tools/grants", dependencies=auth)
    def scoped_grants():
        try:
            return grant_inventory(root)
        except (WorkStop, sqlite3.DatabaseError, OSError) as exc:
            raise HTTPException(503, detail="Private tool grant inventory unavailable") from exc
