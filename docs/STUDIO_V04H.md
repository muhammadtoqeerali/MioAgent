# MioAgent v0.4H — Studio: web research, attachments, vision and image creation

This release closes the gap between a coding-only agent and a general-purpose local-first assistant. **It is a working initial integration, not Claude/GPT feature or intelligence parity.** It preserves the existing v0.4G fleet, dashboard jobs and immutable repository-test controls.

## Conversation entry point

The dashboard gains `/studio` and a visible **STUDIO v0.4H** link on the home page. Studio offers four modes: Chat, Web research, Analyze files, Create image. It uses the pre-existing approved local Model Fleet; no cloud model is contacted.

- **Web research** calls public Bing RSS and, when it returns no usable results, DuckDuckGo Lite. Query strings are sent to the selected public search service. At most six result titles/URLs/snippets are supplied as untrusted reference data labeled `[W1]..[W6]`; the UI renders the source links. **This is snippet-grounded web search, not direct web page fetching, comprehensive agentic research or factual verification**. It fails visibly when both providers are unreachable. Search is triggered in Web research mode, not silently for ordinary chat.
- **Attachments** upload via JSON base64 and are stored at `/var/tmp/mioagent-native-<uid>/studio/attachments` with mode `0600` and SHA-256 integrity checks. Per-file size is 8 MiB, up to six per request. Text, source code, HTML, CSV, TSV, JSON and notebooks get bounded text extraction. DOCX, PPTX, XLSX, ODT and EPUB are read from their zipped XML/text; ZIP gets a *listing only*. PDFs use the optional `pypdf` library for textual extraction (first 30 pages; no image/OCR or rendering). Images PNG/JPEG/WebP/GIF are stored for image interpretation, **not text-extracted**. Unknown binary types are stored and clearly labeled as unreadable; no file types are executed. Larger files, passwords, archive bombs and external resources need future dedicated processors.
- **Image understanding** checks each approved model's Ollama `/api/show` **vision** capability; supported image attachments are sent via native Ollama `/api/chat`. If no approved installed vision model succeeds, a clear error is returned. Two images maximum per request. The API will not send files to a remote vision provider.
- **Image creation** uses a distinct local ComfyUI server at `http://127.0.0.1:8188`, **only after you install ComfyUI and a compatible SD1.x/SDXL `.safetensors` checkpoint yourself**. The CLI `python -m scripts.configure_studio_image` lists local available checkpoints; `--checkpoint 'exact-checkpoint.safetensors'` opts into that exact local checkpoint. The image is produced through ComfyUI's standard nodes, stored privately as PNG, served through an authenticated backend endpoint, and shown in Studio. Jobs are bounded and reports reflect failure/timeouts. **The release does not download, install or claim a usable image model without ComfyUI.** Checkpoints using different architectures such as Flux/Z-Image require a separately implemented graph; do not select those in this initial SD-compatible workflow.
- **Long responses** use a dedicated Next.js `/api/studio` proxy with a longer deadline, retaining host origin checks and private bearer injection. Generated image bytes use a separate token-protected server-side proxy (`/api/studio-image/<id>`). Browser requests never receive the API token.

## After successful deployment

```bash
cd /mnt/hdd16T/ToqeerHomeBackup/toqeer/MioAgent
PY="$HOME/.cache/mioagent/phase1-venv/bin/python"
"$PY" scripts/native_runtime.py status
"$PY" -m scripts.configure_studio_image
```

To enable PDF text extraction if `pypdf` isn't installed in the MioAgent venv, you may explicitly install it (optional network/package-download operation):

```bash
"$PY" -m pip install 'pypdf>=5,<7'
```

For image creation, install and start your own trusted ComfyUI instance on **loopback only** (see https://docs.comfy.org and https://github.com/comfyanonymous/ComfyUI), place a **compatible** checkpoint under ComfyUI's `models/checkpoints`, then run:

```bash
"$PY" -m scripts.configure_studio_image
"$PY" -m scripts.configure_studio_image --checkpoint 'the-listed-compatible-checkpoint.safetensors'
```

Keep Ollama and ComfyUI GPU workloads sequential; Studio uses an advisory fleet lock for managed inference but unmanaged applications can still compete for VRAM. On two 4090 24GB GPUs, model files do not guarantee inference fits with long context or concurrently loaded image checkpoints.

Open `http://127.0.0.1:13000/studio` if Windows port 13000 maps over SSH to Ubuntu's `127.0.0.1:3000`. On Ubuntu check `http://127.0.0.1:3000/studio`. Live served HTML must contain `STUDIO v0.4H` before deployment publishes.

## Known limits and next large increment

This v0.4H Studio does not automatically merge conversations with legacy `/assistant` history. It provides one-request-at-a-time, in-page conversation history; persistence across reloads, resumable image jobs on supervisor restart, streaming responses, multiple web-search rounds, document editing/download, OCR, rich spreadsheets, file previews, PDF page images, TTS/ASR and full browser automation are not yet implemented. To reach Claude/ChatGPT-style reliability, the next iteration needs a durable session/message database, resumable tool jobs, chunking/RAG for larger files, multiple retrieval providers with content verification, and richer permissioned artifacts.

References for publicly observable design patterns:

- Claude Cowork public architecture: https://support.claude.com/en/articles/14479288-claude-cowork-architecture-overview
- Claude computer tool loop: https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool
- Claude web research: https://support.claude.com/en/articles/10684626-enable-and-use-web-search
- Claude supported file types: https://support.claude.com/en/articles/8241126-upload-files-to-claude
- ComfyUI server API: https://github.com/Comfy-Org/docs/blob/main/development/comfyui-server/comms_routes.mdx
