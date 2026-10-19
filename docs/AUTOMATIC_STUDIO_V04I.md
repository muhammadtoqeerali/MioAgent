# MioAgent v0.4I — automatic assistant tool routing

The prior v0.4H Studio required separate manual Chat / Web / Analyze / Image modes. The updated Studio defaults to a **single prompt**: it selects a tool operation based on prompt wording and attachments. For clear image generation, research/current-information requests, attached document analysis and ordinary chat, no mode button is needed. Existing `mode` API values remain accepted for clients that use them. This is bounded, heuristic intent routing, **not** a frontier model agent that can infer every implicit intention.

## Guarantees

- `mio/studio_autoroute.py` classifies clear requests without an extra GPU model call. The server makes the decision; the client sends `mode: auto`. Selected operation is returned for text responses.
- Explicit requests to generate an image send a job to existing local ComfyUI via the Studio API. **This works only after an installed/ready checkpoint is configured; it will never claim an image was created without real image bytes.** The old image job endpoints remain supported.
- Requests for recent/current information or online research trigger actual public web-search calls without a separate UI toggle. Live results depend on workstation DNS/TLS/provider reachability. Results are **snippets**, not verified full pages. No successful result is invented on an HTTP/DNS failure.
- Attached files route to analysis unless the prompt specifically asks for web research or a new image. All earlier attachment size, owner permission and file-integrity rules remain.
- Models, server token, private files, no-cloud policy, code editing approval and sandbox verification retain their previous permissions.

## Diagnose live web search

From the native workstation:

```bash
PY="$HOME/.cache/mioagent/phase1-venv/bin/python"
"$PY" -m scripts.diagnose_studio_web
```

If DNS resolves but no results arrive, Bing RSS or DuckDuckGo Lite may be blocked or change markup. A provider request must genuinely succeed to return citations; this release is not a full browser/research agent. Troubleshoot network separately; do not weaken server authentication or forward private network targets to search providers.

## Make image creation operational (separate opt-in)

The user's previous status showed no configured checkpoint. The Studio update **cannot create a raster without actual model weights**. The included `scripts/bootstrap_studio_image.sh` is a separate, optional installer. Review it before running. It installs ComfyUI and dependencies without sudo, and downloads a pinned 2.13GB SD1.5 FP16 checkpoint from the Comfy-Org archive. Verify licensing (CreativeML OpenRAIL-M) and disk/GPU availability before proceeding. It uses a second GPU by default, but unmanaged Ollama/ComfyUI processes can still contend for VRAM.

```bash
cd /mnt/hdd16T/ToqeerHomeBackup/toqeer/MioAgent
bash scripts/bootstrap_studio_image.sh --install --i-approve-downloads
# In a separate terminal, leave this command running:
bash scripts/bootstrap_studio_image.sh --start
```

Once running on `127.0.0.1:8188`:

```bash
PY="$HOME/.cache/mioagent/phase1-venv/bin/python"
"$PY" -m scripts.configure_studio_image
"$PY" -m scripts.configure_studio_image --checkpoint 'v1-5-pruned-emaonly-fp16.safetensors'
```

Then ask, in the single Studio prompt: `Generate a picture of a friendly robot in a flower garden.` Wait for the private image job to finish. The checkpoint is SD 1.5, **not** equivalent in image quality to newer image generators. Nothing downloads a checkpoint during an ordinary assistant request or publish.

Checkpoint source and SHA-256: https://huggingface.co/Comfy-Org/stable-diffusion-v1-5-archive/blob/82ddc01b8d77adc5b4a7c6b5e8f2ddf1a6fe0c08/v1-5-pruned-emaonly-fp16.safetensors

## Tests / deploy

The full workstation release runs Ruff, the complete Python tests, TypeScript typecheck, Next production build, and local API/browser HTTP checks before commit/push. The release does not automatically install ComfyUI. No write to unrelated untracked files, and no new cloud credentials or APIs.
