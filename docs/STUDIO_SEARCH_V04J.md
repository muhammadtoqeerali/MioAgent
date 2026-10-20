# v0.4J — Search evidence quality, not just search HTTP status

The v0.4I model routing works and the search network is reachable, but a real humanoid-robotics question returned Google/Bing/Yahoo home pages as six 'sources'. Those are not research evidence. GPT-oss appropriately said the snippets did not support the request.

This v0.4J patch changes **only the search adapter**, without altering the existing model fleet, API routes, Studio UI, file ingestion, image tooling or coding engine:

- Remove meta-instructions from the public search query (for example, strip 'Search the web for' and 'and give me three cited findings').
- Reject generic search-engine homepages and off-topic titles/snippets; de-duplicate results and prioritize stronger topical matches.
- Request the fallback provider when the first provider returns *irrelevant* results, not only when it returns zero results.
- Make one bounded shorter-keyword retry when both providers return off-topic evidence. Fail explicitly if no relevant sources are found.
- Preserve `[W1]` citation labels and the existing API result contract. No arbitrary URL crawling, model-initiated network access or cloud LLM calls.

This improves topic relevance, **not** source authenticity, publication recency, the factual correctness of snippets, or the ability to read full articles. A complete research agent still needs date checks, cross-source verification and safe page retrieval. For a current-news question, do not equate keyword relevance with contemporaneous evidence.

## After installing

```bash
cd /mnt/hdd16T/ToqeerHomeBackup/toqeer/MioAgent
PY="$HOME/.cache/mioagent/phase1-venv/bin/python"
"$PY" -m scripts.diagnose_studio_research
```

The diagnostic now uses **the same humanoid-robotics question that failed before**, and prints only topic-matching sources. If the providers remain unhelpful, it exits nonzero and says so. After a successful diagnostic, retry that question at `http://127.0.0.1:13000/studio` and check that the answer cites research sources, not search portals. Date-sensitive facts still need further checking.

## Image generation is an independent setup task

Nothing in this release installs diffusion weights. `available_local_checkpoints: []` means ComfyUI is not running with an advertised checkpoint. Check the already-deployed `scripts/bootstrap_studio_image.sh`: the explicit `--install --i-approve-downloads` action installs ComfyUI and downloads a verified 2.13 GB Stable Diffusion 1.5 model. In another terminal run `--start`, leave it running, then run `python -m scripts.configure_studio_image --checkpoint 'v1-5-pruned-emaonly-fp16.safetensors'`. Do not run that final configuration command before the installer and ComfyUI server have succeeded.
