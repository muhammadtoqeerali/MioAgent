"""Studio v0.4H: private attachments, live evidence, image adapters, auth."""
import asyncio
import base64
import hashlib
import io
import zipfile
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mio import studio_api as api
from mio.studio_files import StudioError, inspect_bytes, read_attachment, save_attachment
from mio.studio_tools import image_workflow, vision_answer, web_search


def private(tmp_path):
    folder = tmp_path / "owned"
    folder.mkdir(mode=0o700)
    return folder


def b64(content):
    return base64.b64encode(content).decode()


def test_text_attachment_roundtrip(tmp_path):
    root = private(tmp_path) / "attachments"
    rec = save_attachment(root, "notes.md", b64(b"Source fact: 42"))
    meta, raw = read_attachment(root, rec["id"])
    assert raw == b"Source fact: 42"
    assert meta["extract"] == "Source fact: 42"
    assert meta["kind"] == "text"
    assert (root / (rec["id"] + ".bin")).stat().st_mode & 0o077 == 0


def test_tampered_attachment_is_rejected(tmp_path):
    root = private(tmp_path) / "attachments"
    rec = save_attachment(root, "doc.txt", b64(b"trusted"))
    (root / (rec["id"] + ".bin")).write_bytes(b"modified")
    with pytest.raises(StudioError, match="integrity"):
        read_attachment(root, rec["id"])


@pytest.mark.parametrize("name", ["../../user.env", "../notes.txt", "/tmp/exploit", ".secret", "a\\b.txt", ""])
def test_unsafe_filename_refused(tmp_path, name):
    with pytest.raises(StudioError):
        save_attachment(private(tmp_path) / "attachments", name, b64(b"hello"))


@pytest.mark.parametrize("file_id", ["../../abc", "fake", "a" * 33, "A" * 32])
def test_unsafe_file_id_refused(tmp_path, file_id):
    with pytest.raises(StudioError):
        read_attachment(private(tmp_path) / "attachments", file_id)


def test_binary_file_is_not_falsely_parsed(tmp_path):
    rec = save_attachment(private(tmp_path) / "files", "payload.bin", b64(b"\x00\xff\x00"))
    assert rec["kind"] == "binary"


@pytest.mark.parametrize("suffix, content", [(".png", b"notpng"), (".pdf", b"notpdf"), (".webp", b"RIFFxxxxwrong")])
def test_reject_mismatched_content(tmp_path, suffix, content):
    with pytest.raises(StudioError):
        save_attachment(private(tmp_path) / "files", "test" + suffix, b64(content))


def test_uploaded_image_is_not_claimed_analyzed(tmp_path):
    kind, summary = inspect_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 20, "x.png")
    assert kind == "image" and "requires" in summary


def test_docx_text_extraction(tmp_path):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as z:
        z.writestr("word/document.xml", '<w:document xmlns:w="urn:w"><w:p><w:t>Robotics data</w:t></w:p></w:document>')
    assert "Robotics data" in inspect_bytes(output.getvalue(), "x.docx")[1]


def test_pptx_text_extraction():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as z:
        z.writestr("ppt/slides/slide1.xml", '<p xmlns:a="urn:a"><a:t>Slide one</a:t></p>')
    assert "Slide one" in inspect_bytes(output.getvalue(), "slides.pptx")[1]


def test_xlsx_text_extraction():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as z:
        z.writestr("xl/sharedStrings.xml", '<si><t>Experiment 12</t></si>')
    assert "Experiment 12" in inspect_bytes(output.getvalue(), "data.xlsx")[1]


def test_zip_traversal_detected():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as z:
        z.writestr("../malicious", "evil")
    with pytest.raises(StudioError):
        inspect_bytes(output.getvalue(), "data.zip")


def test_zip_bomb_metadata_limit():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("large", b"A" * (33 * 1024 * 1024))
    with pytest.raises(StudioError):
        inspect_bytes(output.getvalue(), "data.zip")


@pytest.mark.parametrize("query", ["", "ab", "x" * 360])
def test_invalid_search_query_never_makes_network_call(query):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: pytest.fail("Network call not allowed"))) as client:
            with pytest.raises(StudioError):
                await web_search(query, client)
    asyncio.run(go())


def test_web_rss_citations_and_no_arbitrary_url_fetch():
    called = []
    xml = (b'<?xml version="1.0"?><rss><channel>'
           b'<item><title>Research news</title><link>https://example.org/paper</link><description>New dataset</description></item>'
           b'<item><title>Internal link</title><link>http://127.0.0.1/secrets</link><description>Private</description></item>'
           b'</channel></rss>')

    def handler(request):
        called.append(str(request.url))
        return httpx.Response(200, content=xml)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await web_search("robot research", client)
    result = asyncio.run(go())
    assert len(result) == 1
    assert result[0]["ref"] == "W1"
    assert "robot%20research" in called[0]
    assert len(called) == 1
    assert called[0].startswith("https://www.bing.com/")


def test_web_down_failure_is_explicit():
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(503))) as client:
            with pytest.raises(StudioError, match="unavailable"):
                await web_search("recent developments", client)
    asyncio.run(go())


def test_vision_requires_advertised_capability():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion"]})
        pytest.fail("Image sent to text-only model")

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(StudioError, match="vision"):
                await vision_answer("Explain image", [b"png"], ["qwen3.8:27b"], {"qwen3.8:27b": {}}, client)
    asyncio.run(go())
    assert seen == ["/api/show"]


def test_image_workflow_contains_only_standard_nodes():
    workflow = image_workflow("model.safetensors", "A blue robot", 4)
    assert len(workflow) == 7
    assert workflow["6"]["inputs"]["text"] == "A blue robot"
    assert workflow["3"]["inputs"]["steps"] == 22
    assert workflow["9"]["class_type"] == "SaveImage"


def test_studio_requires_bearer_and_never_discloses_file(tmp_path, monkeypatch):
    root = private(tmp_path)
    app = FastAPI()

    def authorize(authorization: str | None = None):
        # Test dependency implemented as request header via Header.
        return

    from fastapi import Header, HTTPException

    def require_token(authorization: str | None = Header(default=None)):
        if authorization != "Bearer testcase":
            raise HTTPException(401, "Unauthorized")

    class Settings:
        pass

    api.register_studio_routes(app, Settings(), require_token, root)
    monkeypatch.setattr(api, "inventory", AsyncMock(return_value={"gpt-oss:20b": {}}))
    with TestClient(app) as client:
        assert client.get("/api/studio/capabilities").status_code == 401
        assert client.post("/api/studio/attachments", json={"filename": "secret.txt", "base64": b64(b"private")}).status_code == 401
        headers = {"Authorization": "Bearer testcase"}
        assert client.get("/api/studio/capabilities", headers=headers).json()["release"] == "v0.4H"
        saved = client.post("/api/studio/attachments", headers=headers,
                            json={"filename": "data.txt", "base64": b64(b"evidence")})
        assert saved.status_code == 200, saved.text
        file_id = saved.json()["id"]
        assert "evidence" not in saved.text
        assert client.get(f"/api/studio/images/{file_id}", headers=headers).status_code == 404
        assert client.get(f"/api/studio/images/{'f'*32}/file", headers=headers).status_code == 404
        assert client.post("/api/studio/images", headers=headers,
                           json={"prompt": "Generate a blue robot"}).status_code == 409


def test_atomic_image_job_status_and_integrity(tmp_path):
    root = private(tmp_path)
    job_id = "a" * 32
    api._write_job(root, {"id": job_id, "state": "queued"})
    assert api._read_job(root, job_id)["state"] == "queued"
    api._write_job(root, {"id": job_id, "state": "ready", "sha256": "b" * 64})
    assert api._read_job(root, job_id)["state"] == "ready"
    p = api._job_path(root, job_id)
    assert p.stat().st_mode & 0o077 == 0


def test_research_endpoint_injects_real_sources_and_model_cites(tmp_path, monkeypatch):
    root = private(tmp_path)
    app = FastAPI()
    from fastapi import Header, HTTPException

    def require_token(authorization: str | None = Header(default=None)):
        if authorization != "Bearer testcase":
            raise HTTPException(401)

    class Settings:
        pass

    class FakeRouter:
        def __init__(self, _, role):
            assert role == "research"

        async def complete(self, messages, max_tokens=768):
            assert "[W1]" in messages[-1]["content"]
            return type("Result", (), {"text": "The evidence reports a trial [W1].", "model": "gpt-oss:20b"})()

    monkeypatch.setattr(api, "web_search", AsyncMock(return_value=[{
        "ref": "W1", "title": "Example", "url": "https://example.org/paper", "snippet": "New trial"}]))
    monkeypatch.setattr(api, "FleetRouter", FakeRouter)
    api.register_studio_routes(app, Settings(), require_token, root)
    with TestClient(app) as client:
        response = client.post("/api/studio/respond", headers={"Authorization": "Bearer testcase"},
                               json={"mode": "research", "prompt": "What changed in recent trials?", "attachments": []})
    assert response.status_code == 200, response.text
    assert response.json()["sources"][0]["ref"] == "W1"
    assert response.json()["model"] == "gpt-oss:20b"


def test_image_job_response_bytes_are_sha_checked(tmp_path, monkeypatch):
    root = private(tmp_path)
    app = FastAPI()
    from fastapi import Header, HTTPException

    def require_token(authorization: str | None = Header(default=None)):
        if authorization != "Bearer testcase":
            raise HTTPException(401)

    class Settings:
        pass

    api.register_studio_routes(app, Settings(), require_token, root)
    job_id = "a" * 32
    raster = b"\x89PNG\r\n\x1a\n" + b"fakedata"
    api._write_job(root, {"id": job_id, "state": "ready", "sha256": hashlib.sha256(raster).hexdigest()})
    (api._jobs(root) / (job_id + ".png")).write_bytes(raster)
    (api._jobs(root) / (job_id + ".png")).chmod(0o600)
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer testcase"}
        img = client.get(f"/api/studio/images/{job_id}/file", headers=headers)
        assert img.status_code == 200 and img.content == raster
        assert img.headers["content-type"] == "image/png"
        (api._jobs(root) / (job_id + ".png")).write_bytes(b"tampered")
        assert client.get(f"/api/studio/images/{job_id}/file", headers=headers).status_code == 404
