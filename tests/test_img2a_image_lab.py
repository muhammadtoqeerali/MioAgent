"""IMG2A validation: no GPU calls, downloaded models or private source writes."""
from __future__ import annotations

import struct

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from mio.image_lab_api import ImageLabRequest, _image_type, register_image_lab_routes
from mio.image_lab_workflow import StudioError, build_flux


def test_flux_generation_uses_img1c_parameters():
    job = "a" * 32
    graph = build_flux("A realistic standing human", 1234, job)
    assert set(graph) == {str(i) for i in range(10, 23)}
    assert graph["17"]["inputs"] == {"steps": 4, "width": 1024, "height": 1024}
    assert graph["15"]["inputs"]["cfg"] == 1
    assert graph["11"]["inputs"]["type"] == "flux2"
    assert graph["22"]["inputs"]["filename_prefix"] == f"MioAgent_IMG2A_{job}"


def test_flux_edit_references_uploaded_image_in_both_conditioning_branches():
    ref = "mio-img2a-" + "a" * 32 + ".png"
    graph = build_flux("Only change the jacket to cobalt blue", 5, "a" * 32,
                       reference=ref, dimensions=(1200, 800))
    assert graph["23"]["inputs"]["image"] == ref
    assert graph["24"]["inputs"]["pixels"] == ["23", 0]
    assert graph["25"]["inputs"]["latent"] == ["24", 0]
    assert graph["26"]["inputs"]["latent"] == ["24", 0]
    assert graph["15"]["inputs"]["positive"] == ["25", 0]
    assert graph["15"]["inputs"]["negative"] == ["26", 0]
    assert graph["17"]["inputs"]["width"] == 1024
    assert graph["17"]["inputs"]["height"] % 16 == 0


@pytest.mark.parametrize("invalid", ["../secret.png", "user.png", "bad/file.png", "mio-img2a-" + "z"*32 + ".png"])
def test_untrusted_image_paths_rejected(invalid):
    with pytest.raises(StudioError):
        build_flux("Change the picture", 1, "a" * 32, reference=invalid)


def test_png_image_bounds():
    header = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 1024, 1024) + b"\x08\x02\x00\x00\x00" + b"1234"
    assert _image_type(header, "reference.png") == ("png", "image/png", (1024, 1024))
    with pytest.raises(StudioError):
        _image_type(header[:16] + struct.pack(">II", 9999, 9999) + header[24:], "reference.png")


def test_edit_request_model_schema():
    assert ImageLabRequest(prompt="Create a portrait", backend="flux2").backend == "flux2"
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ImageLabRequest(prompt="Create a portrait", backend="third-party")


def test_owner_bearer_required(tmp_path):
    app = FastAPI()
    def auth(authorization: str | None = Header(None)) -> None:
        if authorization != "Bearer local-private-token":
            raise HTTPException(401)
    register_image_lab_routes(app, auth, root=tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/studio/image-lab/capabilities").status_code == 401
        assert client.post("/api/studio/image-lab/jobs", json={"prompt": "A photo"}).status_code == 401
        assert client.get("/api/studio/image-lab/jobs/" + "a"*32).status_code == 401
        assert client.post("/api/studio/image-lab/jobs", headers={"Authorization": "Bearer local-private-token"},
                           json={"prompt": "Change jacket", "backend": "sd15", "attachment": "a"*32}).status_code == 409
