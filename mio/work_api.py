"""Authenticated owner-only API for persistent Work projects and auditable tasks."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

from mio.config import Settings
from mio.studio_files import StudioError
from mio.work_core import (
    RUNTIME,
    SKILLS,
    WorkStop,
    add_memory,
    create_project,
    create_run,
    interrupt_orphaned,
    link_file,
    project_info,
    remove_memory,
    run_info,
)
from mio.work_engineering import read_artifact, zip_artifact
from mio.work_lifecycle import is_archived, listed_projects, register_work_lifecycle


class ProjectNew(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    instructions: str = Field(default="", max_length=6000)


class MemoryNew(BaseModel):
    content: str = Field(min_length=3, max_length=1500)
    approved: Literal[True]


class AssetNew(BaseModel):
    attachment_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class TaskNew(BaseModel):
    prompt: str = Field(min_length=4, max_length=6000)
    task_type: Literal["bounded", "engineering"] = "bounded"
    approved: bool = False


def register_work_routes(app: FastAPI, settings: Settings, require_token: Callable,
                         root: Path = RUNTIME / "work") -> None:
    """Never expose an endpoint to grant filesystem, network or shell permissions."""
    auth = [Depends(require_token)]
    register_work_lifecycle(app, require_token, root)
    # Only the managed native runtime owns the persistent production queue.
    # Unit-test app factories must not interrupt the operator's real Work tasks.
    # Test stores retain their old interruption semantics. In production a
    # separate worker, not FastAPI, owns task lifecycle and restart recovery.
    if root != RUNTIME / "work":
        interrupt_orphaned(root)

    @app.get("/api/work/overview", dependencies=auth)
    def overview(archived: bool = False):
        return {"release": "v0.4K", "projects": listed_projects(root, archived=archived), "skills": SKILLS,
                "permissions": {"host_shell": False, "host_file_scan": False,
                                "arbitrary_browser": False, "public_research": True,
                                "owner_uploaded_files": True, "python_engineering": True},
                "note": "Persistent work sessions; no unrestricted computer access"}

    @app.post("/api/work/projects", dependencies=auth, status_code=201)
    def make_project(payload: ProjectNew):
        try:
            return create_project(root, payload.title, payload.instructions)
        except WorkStop as exc:
            raise HTTPException(422, detail=str(exc)) from exc

    @app.get("/api/work/projects/{project_id}", dependencies=auth)
    def project(project_id: str):
        try:
            return project_info(root, project_id)
        except WorkStop as exc:
            raise HTTPException(404, detail="Project unavailable") from exc

    @app.post("/api/work/projects/{project_id}/memory", dependencies=auth, status_code=201)
    def remember(project_id: str, payload: MemoryNew):
        try:
            return add_memory(root, project_id, payload.content)
        except WorkStop as exc:
            raise HTTPException(422, detail=str(exc)) from exc

    @app.delete("/api/work/projects/{project_id}/memory/{memory_id}", dependencies=auth)
    def forget(project_id: str, memory_id: str):
        try:
            remove_memory(root, project_id, memory_id)
            return {"removed": True}
        except WorkStop as exc:
            raise HTTPException(404, detail="Memory unavailable") from exc

    @app.post("/api/work/projects/{project_id}/files", dependencies=auth, status_code=201)
    def attach(project_id: str, payload: AssetNew):
        try:
            return link_file(root, project_id, payload.attachment_id)
        except (WorkStop, StudioError, OSError, KeyError) as exc:
            raise HTTPException(422, detail="Attachment could not be linked to this project") from exc

    @app.post("/api/work/projects/{project_id}/runs", dependencies=auth, status_code=202)
    async def start_run(project_id: str, payload: TaskNew):
        try:
            if is_archived(root, project_id):
                raise WorkStop("Restore this archived project before starting a run")
            if payload.task_type == "engineering" and not payload.approved:
                raise WorkStop("Explicit approval required for isolated Python engineering")
            run = create_run(root, project_id, payload.prompt,
                             engineering=payload.task_type == "engineering")
        except WorkStop as exc:
            raise HTTPException(409, detail=str(exc)) from exc
        # Persistent worker owns the queue; browser/API process is not a task host.
        return run

    @app.get("/api/work/runs/{run_id}", dependencies=auth)
    def read_run(run_id: str):
        try:
            return run_info(root, run_id)
        except WorkStop as exc:
            raise HTTPException(404, detail="Work run unavailable") from exc

    @app.get("/api/work/runs/{run_id}/files", dependencies=auth)
    def engineering_files(run_id: str):
        try:
            run = run_info(root, run_id)
            if run["mode"] != "engineering" or not run["result"]:
                raise WorkStop("Engineering files are not ready")
            metadata, _files = read_artifact(root, run_id)
            return metadata
        except (WorkStop, OSError, ValueError) as exc:
            raise HTTPException(404, detail="Engineering files unavailable") from exc

    @app.get("/api/work/runs/{run_id}/download", dependencies=auth)
    def engineering_download(run_id: str):
        try:
            run = run_info(root, run_id)
            if run["mode"] != "engineering" or not run["result"]:
                raise WorkStop("Engineering files are not ready")
            archive = zip_artifact(root, run_id)
            return Response(content=archive, media_type="application/zip",
                            headers={"Cache-Control": "no-store", "Content-Disposition":
                                     f'attachment; filename="mio-work-{run_id[:8]}.zip"'})
        except (WorkStop, OSError, ValueError) as exc:
            raise HTTPException(404, detail="Engineering ZIP unavailable") from exc

    @app.get("/api/work/runs/{run_id}/artifact", dependencies=auth)
    def artifact(run_id: str):
        try:
            run = run_info(root, run_id)
        except WorkStop as exc:
            raise HTTPException(404, detail="Work run unavailable") from exc
        if run["state"] not in ("answered", "needs_review") or not run["result"]:
            raise HTTPException(409, detail="No completed draft is available")
        content = "# MioAgent Work task\n\n" + run["prompt"] + "\n\n" + run["result"] + "\n"
        if run["sources"]:
            content += "\n## Retrieved sources (search snippets, not full-page verified)\n"
            for source in run["sources"]:
                content += f"\n- [{source['ref']}] {source['title']}: {source['url']}"
        return Response(content=content, media_type="text/markdown; charset=utf-8",
                        headers={"Cache-Control": "no-store", "Content-Disposition":
                                 f'attachment; filename="mio-work-{run_id[:8]}.md"'})
