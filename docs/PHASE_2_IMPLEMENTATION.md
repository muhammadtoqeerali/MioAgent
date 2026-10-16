# MioAgent Phase 2: Intelligence milestone 0.2.0

**Status:** staged for workstation validation; not fully complete until the first genuine model request passes.

This batch adds a model gateway, an AI supervisor, queue-integrated model tasks, durable conversations, user-approved memory notes, a new `/assistant` dashboard, and tests. It does NOT provide voice control, autonomous shell/browser access, embeddings, or unrestricted self-improvement.

## Architecture

`Browser /assistant → Next.js same-origin proxy → FastAPI bearer auth → SQLite AIJob/Task/Conversation/ChatMessage/MemoryNote → worker → two sequential model calls → persisted result → dashboard polling.`

Model interfaces use OpenAI-compatible `/v1/chat/completions`, supported by Ollama and numerous hosted vendors. HTTP endpoints are admin-configured, not chosen by the model or browser. Local provider URL is restricted to loopback. Cloud provider requires an explicit `MIO_ALLOW_CLOUD=true` plus model/key and HTTPS base URL. This may send conversation content and relevant approved memories to the provider: turn cloud on only with permission.

Model usage is displayed only when upstream reports actual token counts. The supervisor's first call creates a **descriptive plan**; the second generates a text answer. Neither executes tools nor fetches live information. The worker queue is intentionally sequential for now. In-progress AI jobs are requeued on restart, and completed messages are deduplicated by task ID. A restart during a model request may repeat the model call: this can incur new token charges, so cloud remains off by default.

Context retrieval: up to 20 history messages and 18k characters; memory uses predictable keyword overlap against up to 500 manually approved notes. No embedding/vector index is included yet. Phase 2's next batch should benchmark and introduce embeddings after model inference is working.

## Rootless Ollama setup

You can use an existing Ollama binary/server on the workstation. Check with `command -v ollama` and `curl -s http://127.0.0.1:11434/api/tags`. If absent, the optional user-space setup script `scripts/setup_ollama_rootless.sh` downloads the official Linux archive and extracts it to a private native Linux directory. It may download hundreds of megabytes. It requires `curl`, `tar`, `zstd`, and `nvidia-smi`. If the workstation lacks `zstd`, install it in an available user environment or obtain administrator help; do not change privileged system folders.

In one workstation terminal, run the installed `ollama serve` with `OLLAMA_HOST=127.0.0.1:11434` and `OLLAMA_MODELS` set to a chosen model directory (large weights can be on your data drive). Then pull a model (for example `gpt-oss:20b` or start with a smaller `qwen3:8b`). The 4090 cards have **separate** 24 GiB VRAM allocations; check actual GPU use with `nvidia-smi`. For a tested initial release, select one model first instead of automatically loading multiple models.

Configure MioAgent with:

```bash
python3 scripts/configure_model.py gpt-oss:20b
python3 scripts/native_runtime.py stop
python3 scripts/native_runtime.py start
python3 scripts/native_runtime.py status
```

From the Windows laptop, keep the SSH tunnel to workstation port 3000 and open `http://127.0.0.1:13000/assistant`.

## Verification and release criteria

- Existing Phase 1 API and dashboard still work.
- `python -m pytest -q` and `python -m ruff check mio tests scripts` pass.
- `npm --prefix apps/dashboard run typecheck` and `npm --prefix apps/dashboard run build` pass.
- Native smoke verifies API + proxy + persistent tasks.
- AI suite tests model routing with mocks (no downloads or external calls).
- A real local model is reachable in `GET /api/assistant/status` and `python3 scripts/phase2_smoke.py` generates an actual completed text reply.
- Local repo is committed/pushed to GitHub only after passing the above tests.

## Security limits

Dashboard and API remain bound to workstation loopback; access via SSH tunnel only. Native runner stores credentials and SQLite under an owner-only `/var/tmp` directory, which is not permanent and can be purged. NTFS project source is writable under permissive mount options. This is suitable only for trusted development; do not attach sensitive accounts or turn on computer-control agents until dedicated isolation is established. GitHub credentials and model API keys never belong in Git.
