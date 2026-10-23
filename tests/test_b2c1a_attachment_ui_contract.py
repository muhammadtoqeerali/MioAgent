"""B2C1A regression: ordinary Chat attachment UI and private PNG saving."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_chat_supports_private_upload_with_preview_and_removal():
    chat = _source("apps/dashboard/app/chat/page.tsx")
    assert '"studio/attachments"' in chat
    assert 'type="file" multiple hidden' in chat
    assert 'title="Attach images or documents"' in chat
    assert "URL.createObjectURL(file)" in chat
    assert "URL.revokeObjectURL" in chat
    assert "onDragOver=" in chat
    assert "onDrop=" in chat
    assert "onPaste=" in chat
    assert "MAX_FILE = 8 * 1024 * 1024" in chat
    assert "files.length + selectedFiles.length > 6" in chat


def test_chat_attachment_uses_authorized_studio_and_automatic_flux2():
    chat = _source("apps/dashboard/app/chat/page.tsx")
    image_client = _source("apps/dashboard/app/_mio/omni-image.tsx")
    backend = _source("mio/omni_images.py")

    # Non-image files remain subject to the established authenticated Studio route.
    assert 'if(files.length)' in chat
    assert 'fetch("/api/studio"' in chat
    assert 'attachments:files.map(f=>f.id)' in chat
    assert 'mode:"auto"' in chat
    assert 'setFileTurns(prev=>' in chat
    assert 'File-assisted answers in this preview are visible here' in chat

    # Natural image requests/edit references use the new private FLUX.2 conversation API.
    assert 'await imageIntent(content,"chat",selected,reference?.id??null)' in chat
    assert 'await sendImage(content,"chat",selected,reference?.id??null' in chat
    assert 'reference?"edit":imageMode?"create":"auto"' in chat
    assert 'm.content.startsWith("MIO_IMAGE_TURN:")' in chat
    assert 'OmniImageView id={m.content.slice(' in chat
    assert 'return mioApi("omni/intent", postJson(' in image_client
    assert 'return mioApi("omni/images", postJson(' in image_client
    assert 'fallback_to_sd15=False' in backend
    assert 'Image editing is not yet enabled' not in chat
    assert 'Image editing is not enabled by the current local checkpoint' not in chat
    assert 'Image creation and reference editing use FLUX.2 automatically.' in chat


def test_image_download_is_explicit_and_attachment_is_private():
    chat = _source("apps/dashboard/app/chat/page.tsx")
    studio = _source("apps/dashboard/app/studio/page.tsx")
    proxy = _source("apps/dashboard/app/api/studio-image/[id]/route.ts")
    assert "?download=1" in chat
    assert "?download=1" in studio
    assert "↓ Download PNG" in chat
    assert "↓ Download PNG" in studio
    assert 'req.nextUrl.searchParams.get("download")' in proxy
    assert '"Content-Disposition"' in proxy
    assert 'id = (await ctx.params).id' in proxy
    assert 'Authorization: `Bearer ${token}`' in proxy
    assert 'process.env.VERCEL === "1"' in proxy


def test_unified_png_proxy_is_private_and_download_explicit():
    proxy = _source("apps/dashboard/app/api/mio-image/[id]/route.ts")
    omni = _source("mio/omni_images.py")
    assert 'process.env.VERCEL === "1"' in proxy
    assert 'process.env.MIO_API_URL!=="http://127.0.0.1:8000"' in proxy
    assert 'Authorization:`Bearer ${process.env.MIO_API_TOKEN}`' in proxy
    assert 'process.env.MIO_API_TOKEN' in proxy
    assert 'req.nextUrl.searchParams.get("download")==="1"' in proxy
    assert '"Content-Disposition"' in proxy
    assert '"Cache-Control":"private, no-store"' in proxy
    assert '"X-Content-Type-Options":"nosniff"' in proxy
    assert '@app.get("/api/omni/images/{turn_id}/file", dependencies=auth)' in omni
    assert 'if not HEX32.fullmatch(turn_id):' in omni
    assert 'if item is None:' in omni
    assert 'content=data, media_type="image/png"' in omni
