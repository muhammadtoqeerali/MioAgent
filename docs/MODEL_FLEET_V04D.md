# MioAgent v0.4D — Multi-model intelligence fleet (large integrated release)

**Architecture:** local-first, task-role-specific, benchmark-informed model routing with
bounded fallback, independent second-model critique, and existing engineering-mode integration.
**Not a claim** of GPT-6 Astra, Claude Opus, or Gemini frontier parity. A high-quality
agent needs tools, state, retrieval, correct context, evaluation and capable models;
merely downloading weights cannot duplicate closed proprietary frontier models.

## What is working after installing the release

- `mio.model_fleet`: discovers real **installed** Ollama models from loopback `/api/tags`, verifies model SHA-256 digest stability, rejects aliases tagged as cloud, stores owner-private per-role allowlists with baseline-verified benchmark report hash, and routes requests with local-only `ModelRouter` in sequence (up to 3 selected models). Bounded fallback is triggered by inference failure; drafting also advances the model after *trusted draft validation* rejects the response. No per-task user permission escalation.
- Seven roles: `chat`, `planning`, `coding`, `repair`, `review`, `writing`, `research`. Operator may activate an explicit fallback order, or `--auto` uses only four clearly-labeled **static format/constraint probes** (NOT a code-quality or frontier benchmark) to set different role priorities. Default without policy remains unchanged `gpt-oss:20b`.
- Existing engineering planner can now use the selected `planning` model; project drafting selects `coding`, repairs use `repair`, and Chat worker selects `chat`. The original immutable acceptance tests, bubblewrap and existing bounded repairs remain the acceptance authority.
- CLI `ask` supports writing and evidence-grounded research (with a user-provided context file). `--review` invokes a **distinct** approved local model, if available, to critique the response. `--refine` adds one bounded revision after that critique. Review is advice; never presented as verified tests or trustworthy sources. No web research/scraping capability yet.
- Private `model-fleet.json` in `/var/tmp/mioagent-native-<uid>` is 0600 on native Linux; reports are private. The lock `model-fleet.lock` prevents overlapping *fleet-managed* inference. Other independent clients calling Ollama do not honor this lock, and GPU pinning must be verified separately.
- CLI `disable` safely archives the policy and restores legacy single-model behavior for subsequent tasks. Installation itself leaves policy disabled and **does not** download models, access the internet, or use academic GPUs.

## Important reality check: models

Verified previous workstation installation: `gpt-oss:20b` (~14 GB Ollama weights). Candidates for your 2x RTX 4090 (24 GB each) are `qwen3.5:9b` (~7 GB), `qwen3.8:27b` (~18 GB), `gemma4:12b`, and other small quantized weights as available. Size is disk/model-file estimate, **not total VRAM at your selected context length**. One Qwen 27B at 18 GB may fit on an RTX 4090 for modest context but needs GPU telemetry and benchmarking, particularly for long prompts. Do not presume two large models fit simultaneously on one GPU. GLM 5.3, Kimi K3, DeepSeek V4 and MiniMax M3 flagship-class full weights need far larger memory/serving budgets, or explicitly authorized remote services. Closed models (Claude Opus/Sonnet, GPT-6 Astra, Gemini 4 Argon) **cannot be installed as open local weights**; any remote integration requires authorized account/API, usage terms and explicit paid or free-tier policy. `free-claude-code`, ECC skills, and LM Studio are frameworks/skills/servers, not replacements for weights.

References for model candidates:
- https://ollama.com/library/gpt-oss
- https://ollama.com/library/qwen3.8
- https://ollama.com/library/qwen3.5
- https://ollama.com/library/gemma4

## Workstation commands after published v0.4D release

First **inventory only** (no GPU inference, download, cloud, writes outside private runtime):

```bash
cd /mnt/hdd16T/ToqeerHomeBackup/toqeer/MioAgent
PY="$HOME/.cache/mioagent/phase1-venv/bin/python"
"$PY" -m scripts.model_fleet inventory
```

If you approve optional **sizeable downloads** (confirm disk space, network policy, and current Ollama availability), run manually and sequentially:

```bash
ollama pull qwen3.5:9b
ollama pull qwen3.8:27b
```

Those are options, **never prerequisites** for the v0.4D deployment. `ollama pull` can use tens of GB of bandwidth/disk, and a local Ollama daemon must be running. Models are downloaded to Ollama storage, not KIOS. If storage is limited, start with `qwen3.5:9b` and benchmark it against `gpt-oss:20b`.

Benchmark **only installed models** (4 tiny format/constraint probes/model, no code execution, no external sources):

```bash
"$PY" -m scripts.model_fleet benchmark gpt-oss:20b qwen3.5:9b qwen3.8:27b
```

This prints a private benchmark path and its SHA-256. Review the private JSON output. Then enable task-specific preferred ordering with the exact report path:

```bash
"$PY" -m scripts.model_fleet activate --report /var/tmp/mioagent-native-1002/model-benchmarks/fleet-YOUR-REPORT.json --auto
"$PY" -m scripts.model_fleet show
```

`--auto` uses best **tiny-probe** result then lower measured probe latency for the corresponding role. You can instead explicitly select a priority order:

```bash
"$PY" -m scripts.model_fleet activate --report /var/tmp/mioagent-native-1002/model-benchmarks/fleet-YOUR-REPORT.json qwen3.8:27b gpt-oss:20b
```

Activation is one-way until disabled, not silent. `--auto` and explicit models are mutually exclusive. No ongoing daemon configuration edit or restart is needed because each new task reloads the private policy.

Example writing / research without Internet access:

```bash
# Create a simple UTF-8 task prompt in an existing non-symlink file
"$PY" -m scripts.model_fleet ask --role writing --prompt-file /absolute/private/task.txt --review --refine
"$PY" -m scripts.model_fleet ask --role research --prompt-file /absolute/private/task.txt --context-file /absolute/private/evidence.txt --review
```

For real engineering, create a **fresh goal JSON**, with different requirements from previous demo (goal SHA prevents replay), and run `engineer_project.py`. Its plan, coding and repair stages will use model preferences when active, but **the only truth of correctness is still the user's acceptance tests and sandbox output**. New code is never pushed to GitHub automatically by engineering mode.

To return to baseline routing:

```bash
"$PY" -m scripts.model_fleet disable
```

## Constraints and next major development chunk

- The four probes compare formatting/latency only. Proper coding evaluation should use reproducible held-out SWE-bench-style local bugfix tasks, pass@1, unit/integration tests, cost, time and VRAM; writing requires blind quality rubrics; research requires retrieval, grounded citations, and source validation. No unsupported model superiority claim.
- Model fleet is a **controller, not a magic release of closed model weights**. Proprietary frontier models require separate, authorized endpoints. No policy bypasses, no credential extraction, no unrestricted deployment privilege or harmful-action grant.
- Future work: real repository-scoped tools (search/read/patch/test/git) with branch-based change review; robust context retrieval; browse/research under explicit scopes; dynamic context budgets and real reviewer evidence; private durable task checkpoints; richer agent UI; selectively vetted ECC skills loaded per task. These are not falsely claimed implemented by v0.4D.
