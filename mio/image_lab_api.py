"""IMG2A: owner-authenticated Image Lab; FLUX.2 edits and SD1.5 generation fallback.

No changes to default checkpoint, local model policy, existing Studio endpoints or Chat.
Image input comes only from integrity-checked private attachments, never arbitrary paths.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
import struct
import uuid
from collections.abc import Callable
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from mio.image_lab_workflow import EDIT_REQUIRED, ENCODER, REQUIRED, UNET, VAE, build_flux
from mio.model_fleet import inference_lock
from mio.studio_api import RUNTIME, _jobs, _read_job, _studio, _write_job
from mio.studio_files import StudioError, read_attachment
from mio.studio_tools import IMAGE_URL, available_checkpoints, comfy_settings, generate_raster

PNG = b"\x89PNG\r\n\x1a\n"
MAX_PNG = 8 * 1024 * 1024


class ImageLabRequest(BaseModel):
    prompt: str = Field(min_length=4, max_length=1200)
    backend: str = Field(default="flux2", pattern=r"^(flux2|sd15)$")
    attachment: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    fallback_to_sd15: bool = True


def _image_type(data: bytes, name: str) -> tuple[str, str, tuple[int, int]]:
    """PNG/JPEG only; structural header checks and bounded dimensions before ComfyUI."""
    if name.lower().endswith(".png") and len(data) >= 33 and data.startswith(PNG) and data[12:16] == b"IHDR":
        width, height = struct.unpack(">II", data[16:24])
        extension, mime = "png", "image/png"
    elif name.lower().endswith((".jpg", ".jpeg")) and data.startswith(b"\xff\xd8\xff"):
        width = height = 0
        offset = 2
        while offset + 4 < len(data):
            if data[offset] != 0xff:
                break
            marker = data[offset + 1]
            if marker in (0xd8, 0xd9, 0x01) or 0xd0 <= marker <= 0xd7:
                offset += 2
                continue
            seg = int.from_bytes(data[offset+2:offset+4], "big")
            if seg < 2 or offset + 2 + seg > len(data):
                break
            if marker in (0xc0, 0xc1, 0xc2, 0xc3) and seg >= 7:
                height = int.from_bytes(data[offset+5:offset+7], "big")
                width = int.from_bytes(data[offset+7:offset+9], "big")
                break
            offset += seg + 2
        extension, mime = "jpg", "image/jpeg"
    else:
        raise StudioError("FLUX.2 editing currently requires a PNG or JPEG reference")
    if not 256 <= width <= 2048 or not 256 <= height <= 2048 or width * height > 3_000_000:
        raise StudioError("Use a PNG/JPEG between 256 and 2048 pixels (max 3 megapixels)")
    return extension, mime, (width, height)


async def _node_options(client: httpx.AsyncClient, cls: str, field: str) -> list:
    response = await client.get(f"{IMAGE_URL}/object_info/{cls}")
    response.raise_for_status()
    settings = response.json().get(cls, {}).get("input", {})
    option = settings.get("required", {}).get(field, settings.get("optional", {}).get(field, []))
    return option[0] if isinstance(option, list) and option and isinstance(option[0], list) else []


async def flux_available(client: httpx.AsyncClient) -> bool:
    try:
        for cls, key, value in (("UNETLoader", "unet_name", UNET),
                                ("CLIPLoader", "clip_name", ENCODER),
                                ("CLIPLoader", "type", "flux2"),
                                ("VAELoader", "vae_name", VAE)):
            if value not in await _node_options(client, cls, key):
                return False
        for cls in (*REQUIRED, *EDIT_REQUIRED):
            reply = await client.get(f"{IMAGE_URL}/object_info/{cls}")
            reply.raise_for_status()
            if cls not in reply.json():
                return False
        return True
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return False


async def sd15_available(root: Path) -> tuple[bool, str]:
    conf = comfy_settings(_studio(root))
    if conf is None:
        return False, ""
    checkpoint = conf["checkpoint"]
    return checkpoint in await available_checkpoints(), checkpoint


def _active_jobs(root: Path) -> None:
    for record in _jobs(root).glob("*.json"):
        if record.is_symlink() or not record.is_file() or record.stat().st_size > 8192:
            raise StudioError("Unsafe image job in private store")
        if json.loads(record.read_text(encoding="utf-8")).get("state") in ("queued", "running"):
            raise StudioError("Another Studio image job is active")


async def _render_flux(prompt: str, image: bytes | None, file_name: str | None,
                       size: tuple[int, int] | None, job_id: str) -> bytes:
    """Submit tested ComfyUI topology; never accept generated file paths from the user."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=5), trust_env=False,
                                 follow_redirects=False) as client:
        with inference_lock():
            queue = (await client.get(f"{IMAGE_URL}/queue")).json()
            if queue.get("queue_running") or queue.get("queue_pending"):
                raise StudioError("ComfyUI is busy; retry later")
            reference = None
            if image is not None:
                assert file_name is not None
                ext, mime, _ = _image_type(image, file_name)
                reference = f"mio-img2a-{job_id}.{ext}"
                upload = await client.post(f"{IMAGE_URL}/upload/image",
                                           data={"type": "input", "overwrite": "false"},
                                           files={"image": (reference, image, mime)})
                upload.raise_for_status()
                answer = upload.json()
                if (answer.get("name") != reference or answer.get("subfolder", "") != ""
                        or answer.get("type", "input") != "input"):
                    raise StudioError("ComfyUI did not accept the expected reference filename")
            graph = build_flux(prompt, secrets.randbits(48), job_id, reference=reference,
                               dimensions=size or (1024, 1024))
            response = await client.post(f"{IMAGE_URL}/prompt", json={
                "prompt": graph, "client_id": str(uuid.uuid4())})
            response.raise_for_status()
            token = response.json().get("prompt_id")
            if not isinstance(token, str) or not re.fullmatch(r"[a-f0-9-]{36}", token):
                raise StudioError("ComfyUI did not accept the FLUX.2 workflow")
            for _ in range(180):
                await asyncio.sleep(2)
                reply = await client.get(f"{IMAGE_URL}/history/{token}")
                reply.raise_for_status()
                history = reply.json().get(token, {})
                if history.get("status", {}).get("status_str") == "error":
                    raise StudioError("FLUX.2 workflow failed in ComfyUI")
                output = history.get("outputs", {}).get("22", {}).get("images", [])
                if output:
                    if len(output) != 1:
                        raise StudioError("Unexpected ComfyUI output count")
                    meta = output[0]
                    filename = meta.get("filename", "")
                    if (not isinstance(filename, str)
                            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,180}", filename)
                            or not filename.startswith(f"MioAgent_IMG2A_{job_id}")
                            or meta.get("subfolder", "") != "" or meta.get("type") != "output"):
                        raise StudioError("Unexpected ComfyUI output metadata")
                    response = await client.get(f"{IMAGE_URL}/view", params={
                        "filename": filename, "subfolder": "", "type": "output"})
                    response.raise_for_status()
                    raw = response.content
                    if len(raw) > MAX_PNG or not raw.startswith(PNG):
                        raise StudioError("FLUX.2 output is not a bounded PNG")
                    return raw
            raise StudioError("FLUX.2 timed out; inspect ComfyUI history")


async def _execute(root: Path, job_id: str, payload: ImageLabRequest, selected: str,
                   checkpoint: str, image: bytes | None, name: str | None,
                   dimensions: tuple[int, int] | None, fallback: bool) -> None:
    record = {"id": job_id, "state": "running", "backend": selected,
              "operation": "edit" if image else "generate", "fallback_used": fallback, "error": None}
    _write_job(root, record)
    try:
        if selected == "sd15":
            raster = await generate_raster(payload.prompt, checkpoint)
        else:
            raster = await _render_flux(payload.prompt, image, name, dimensions, job_id)
        if len(raster) > MAX_PNG or not raster.startswith(PNG):
            raise StudioError("Image output is not a bounded PNG")
        location = _jobs(root) / (job_id + ".png")
        fd = os.open(location, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as target:
            target.write(raster)
            target.flush()
            os.fsync(target.fileno())
        record.update(state="ready", sha256=hashlib.sha256(raster).hexdigest(), bytes=len(raster))
    except Exception as exc:  # noqa: BLE001 - error recorded without exposing private paths
        record.update(state="failed", error=f"{type(exc).__name__}: image job failed; check ComfyUI diagnostics")
    _write_job(root, record)


def register_image_lab_routes(app: FastAPI, require_token: Callable, root: Path = RUNTIME) -> None:
    auth = [Depends(require_token)]

    @app.get("/api/studio/image-lab/capabilities", dependencies=auth)
    async def lab_capabilities():
        try:
            old, _ = await sd15_available(root)
        except (StudioError, OSError, ValueError):
            old = False
        async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
            new = await flux_available(client)
        return {"default": "flux2", "backends": [
            {"id": "sd15", "name": "SD1.5 (legacy)", "available": old,
             "generation": True, "editing": False},
            {"id": "flux2", "name": "FLUX.2 Klein 4B", "available": new,
             "generation": True, "editing": True}]}

    @app.post("/api/studio/image-lab/jobs", dependencies=auth, status_code=202)
    async def lab_generate(payload: ImageLabRequest):
        try:
            is_edit = payload.attachment is not None
            if is_edit and payload.backend == "sd15":
                raise StudioError("SD1.5 cannot edit images. Choose FLUX.2 Klein.")
            raw = None
            name = None
            dimensions = None
            if is_edit:
                meta, raw = read_attachment(_studio(root) / "attachments", payload.attachment)
                if meta["kind"] != "image":
                    raise StudioError("Editing requires an image attachment")
                name = meta["name"]
                _, _, dimensions = _image_type(raw, name)
            old, checkpoint = await sd15_available(root)
            async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
                flux = await flux_available(client) if payload.backend == "flux2" else False
            backend = payload.backend
            fallback = False
            if backend == "flux2" and not flux:
                if not is_edit and old and payload.fallback_to_sd15:
                    backend, fallback = "sd15", True
                else:
                    raise StudioError("FLUX.2 unavailable; editing has no SD1.5 fallback")
            if backend == "sd15" and not old:
                raise StudioError("Configured SD1.5 checkpoint is unavailable")
            _active_jobs(root)
            job_id = uuid.uuid4().hex
            _write_job(root, {"id": job_id, "state": "queued", "backend": backend,
                              "fallback_used": fallback, "operation": "edit" if is_edit else "generate",
                              "error": None})
            task = asyncio.create_task(_execute(root, job_id, payload, backend, checkpoint,
                                                raw, name, dimensions, fallback))
            app.state.image_lab_jobs = getattr(app.state, "image_lab_jobs", set())
            app.state.image_lab_jobs.add(task)
            task.add_done_callback(app.state.image_lab_jobs.discard)
            return {"id": job_id, "state": "queued", "backend": backend,
                    "fallback_used": fallback, "operation": "edit" if is_edit else "generate"}
        except (StudioError, OSError, ValueError, KeyError, TypeError) as exc:
            raise HTTPException(409, detail=str(exc)[:180]) from exc

    @app.get("/api/studio/image-lab/jobs/{job_id}", dependencies=auth)
    def lab_status(job_id: str):
        try:
            info = _read_job(root, job_id)
            if info.get("backend") not in {"flux2", "sd15"}:
                raise StudioError("Not an Image Lab job")
            return {key: info.get(key) for key in
                    ("id", "state", "backend", "operation", "fallback_used", "error", "sha256", "bytes")}
        except (StudioError, OSError, ValueError, FileNotFoundError) as exc:
            raise HTTPException(404, detail="Image Lab job not found") from exc

    # IMG3A: unified native image turns share the verified FLUX.2 Image Lab runner.
    from mio.omni_images import register_omni_routes
    register_omni_routes(app, require_token, root, lab_generate, ImageLabRequest)
