# MioAgent — Unified Intelligence and Skills Roadmap

**Proposal, 17 October 2026.** This extends the locked `docs/MASTER_PLAN.md` and existing decisions; it does **not** silently replace that plan. Based on validated workstation release `0f0af58` (v0.3D). User goal: a high-quality, autonomous engineering agent that can own approved projects from requirements to verified deliverables, while also supporting a simple chat mode. Open-weight inference should avoid paid API dependencies by default and should consume the minimum GPU/storage resources that do the job.

## 1. Architectural decision

One MioAgent identity and authorization system, **two user-visible modes**:

- **Chat**: questions, learning, research summaries, explanations; no project edits or tool runs without authorization.
- **Project**: durable goal with acceptance criteria, planner, approved workspace, bounded implement/test/repair/review loop, checkpoints and a deliverable manifest. Ownership does not imply unrestricted machine permissions.

Recommended separation:

```text
Local/private UI OR protected Vercel UI
           | HTTPS authenticated gateway (not yet implemented)
Private workstation control plane: auth, projects, jobs, policies, audit, approvals
           | read-only metadata router, measured capability catalog
           +-- local Ollama inference: gpt-oss:20b baseline; Qwen3-8B if benchmarked
           +-- approved skills -> scoped context; reviewed tools -> permission broker
           +-- planner / coding worker / independent verifier / researcher
           +-- Bubblewrap project sandbox (limited Python unittest today)
           +-- durable DB + encrypted backups on native Linux filesystem (future)
           +-- optional university GPU workers (only after IT authorization)
```

Never expose localhost bearer secrets through the Vercel frontend, and never run long jobs inside a Vercel function. UI deployment is separate from agent execution. The current Vercel API proxy correctly refuses privileged online calls pending a secure bridge.

## 2. What external resources actually add

| Candidate | Verified source | Role and decision |
|---|---|---|
| Qwen3-8B (user called it 'Qwen 3.8') | https://huggingface.co/Qwen/Qwen3-8B | Apache-2.0 small local candidate; test coding/tool-calling and quantization before loading. Do not replace gpt-oss on a claim alone. |
| LM Studio / llmster | https://lmstudio.ai/docs/developer | Optional compatible inference backend, not an intelligence booster by itself. Keep Ollama default. No duplicate model-weight downloads. |
| GLM-5.2 | https://huggingface.co/zai-org/GLM-5.2 | Open-weight flagship ~753B parameters. Research/inference-provider option, not a practical local deployment on 2x4090 + shared V100s. No automatic download. |
| Free Claude Code | https://github.com/doggie/free-claude-code | Third-party proxy/harness integration candidate, not Claude's weights or a free Claude license. Test separately and check downstream licensing and service terms. |
| ECC | https://github.com/affaan-m/ECC | Large evolving open-source catalog (reported ~286 skills in a recent snapshot). Study AGENTS.md, rules, planners, TDD, reviewers, security and evaluation. Do **not** globally install hundreds of instructions or hooks. |
| find-skills | https://skills.sh/vercel-labs/skills/find-skills | Skill discovery aid only. Search and show provenance, but don't `npx skills add` unattended. |
| chief-of-staff | https://skills.sh/mattpocock/skills/chief-of-staff | Long-horizon decomposition; extract reviewed patterns, do not grant authority to spawn independent workers. |
| anatomy | https://github.com/wheresryan22/anatomy | Optional technical explanatory diagrams, not core coding path. |
| teach | https://skills.sh/paololeonardi/mattpocock-skills/teach | Multi-session instruction/learning workflows, when explicitly requested. |
| ponytail | https://github.com/DietrichGebert/ponytail | Complexity control / smallest viable implementation; require tests and security regardless. |
| RTK | https://github.com/rtk-ai/rtk | External output summarizer; must retain raw test/error logs separately, never hide warnings in evaluation. Review executable before enabling. |
| graphify | https://github.com/deco31416/graphify | Knowledge graph / code navigation candidate; inspect source, dependency and whether any content goes to third-party services before use. |
| OmniRoute | https://github.com/diegosouzapw/OmniRoute | Routing platform + Agent Skills catalog, not a drop-in source of model intelligence. Evaluate only if own thin router proves inadequate. |
| `CLAUDE-FABLE-5.1.MD` | exact repository/path **unverified** | Do not import unknown file as system prompt. Read official https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-fable-5-1 for high-level practices; tailor and benchmark with local models. |
| Unspecified 'AGENTS.md' Claude coding setup | unknown; ECC verified `AGENTS.md` at https://github.com/affaan-m/ECC/blob/main/AGENTS.md | Study ECC's public version; ask for exact link before adopting any different file. Preserve MioAgent's existing AGENTS.md and locked plan. |

Skill count changes over time; no fixed number is an endorsement. Third-party content is lower-trust input and may include hidden network commands, secret exfiltration, prompt injection, and hooks. A file called `SKILL.md` is not executable permission.

## 3. Model selection and resource usage

1. Keep one RTX 4090 active by default for `gpt-oss:20b`. No automatic power-up of a second local GPU, and no university GPU use. Compute budget is enforced separately from metadata recommendations; this v0.3E registry itself does **not** control the GPU scheduler.
2. Test Qwen3-8B **as a candidate** in an isolated, manually scheduled benchmark. Model must have an approved license, quantization, context budget, structured response quality and no test contamination. Keep one heavyweight model loaded at a time by default to avoid VRAM contention.
3. Local decision = first measure correctness/acceptance pass rate, then optimize latency, token use and energy. Do not assume model size equals capability. Keep evaluation traces and explicit reasons for every role-to-model change.
4. GLM-5.2 / frontier reference models are research comparators or optional external endpoints, **not** transparent free local deployments. Cloud spend stays at $0. Remote V100 baseline is 0 allocated; two maximum only when explicit site permission, routing and storage policies are verified.
5. Treat LM Studio as an alternative to Ollama, not a second required server. Never duplicate model caches without inventory/approval. Add an adapter only when needed.

## 4. Skills and plugin supply chain

Status lifecycle: `discovered -> fetched-to-quarantine -> integrity-recorded -> human/security-reviewed -> benchmarked -> approved-for-specified-role -> active-version-pinned`. Revocation must disable a skill immediately. Never grant permissions because content requests them.

- Registry loads **metadata only** by default (name, source, skill/task tags, required capabilities, version/commit hash, dependencies, audit date). Do not eagerly inject hundreds of prompt files into system context.
- Task router may retrieve up to 2 reviewed **instruction-only** skills; content is passed as quoted, untrusted task context, not system or developer authority. Tool-like skills require a separate audited adapter and permission broker.
- Fetch pinned commits to a private quarantine on a **native Linux** filesystem; validate license, content digest, extra scripts, executable bits, installation hooks, network destinations, secrets behavior, external commands, and update policy. Don't use `curl | bash` or `npx -y` unattended.
- Keep original raw logs, full tests and source diffs; RTK-style compression should be an **optional display layer**, never the source of truth for failure classification.
- Reuse ECC planning/TDD/security patterns selectively; neither AGENTS.md nor third-party `SKILL.md` can override MioAgent's own security controls.

## 5. Claude-like dashboard redesign (functional parity, original design)

Do a lawful feature/interaction comparison using publicly visible UX and owned test accounts: responsive chat, conversation history, streaming, code/files preview, task timeline, project workspaces, deliverable diff, approvals, model/task status, skills used, persistent checkpoints, GPU/storage budgets, and run audit. Recreate **capabilities and interaction principles**, not proprietary source code, branding, hidden APIs, copied assets, or unapproved scraping. Prefer small reusable components over a visual clone.

Deploy frontend from GitHub -> Vercel. Workstation remains the private AI engine. Add login/session authentication + outbound-only private gateway with revocation, rate limiting and per-action authorization **before** enabling remote agent tools.

## 6. Delivery order and testable gates

**v0.3D validation (now)** — Run disposable task end-to-end and record whether two bounded repair attempts succeed, stall or stop; keep immutable acceptance-test hashes. Independent requirement coverage matters: a test count of 1 cannot certify a spec asking for 3 test cases.

**v0.3E (this package)** — Metadata registry, dry-run model/role selection, offline SKILL.md risk scanner, comprehensive plan; no model download or skill execution. Focused tests must pass + workstation full pytest/Ruff + GitHub release.

**v0.3F durability** — Migrate SQLite + approved artifacts away from `/var/tmp` to a user-private native ext4 directory; explicit backups, restore drills, WAL coordination, capacity reservations, per-project quotas, retention and recovery after reboot. Never silently delete current data.

**v0.4 model/skill benchmarking** — Controlled 8B vs 20B tests: unit bug-fixing, multi-file feature, bug triage, API design, documentation, long context, tool-call JSON. Measure pass@1, passing *independent* tests, requirement coverage, wall time, peak VRAM, disk footprint, failure types. Use held-out cases. Add reviewed `find-skills`, ECC planner/security patterns and `ponytail` only if gains appear.

**v0.5 tool-enabled engineering** — Expanded isolated workspace with bounded write access, package/network allowlists by project, manual approval for irreversible actions, fail-closed sandbox, repos/branches/PRs, browser read-only research first and later controlled interactions. Introduce reviewer agent that cannot edit tests to pass.

**v0.6 project autonomy** — Durable planner/executor/reviewer state machine with explicit Chat vs Project mode, per-task model routing, checkpoint/restart, human approvals for risk boundaries, accepted tests held independently, and terminal artifacts. Budget for up to 3 bounded retries; stop on repetition or non-progress.

**v0.7 online interface** — Authenticated Vercel interface with private workstation relay, audit and background job notifications; no public API proxy to GPU tools.

**Later:** optional university compute only after site/IT written guidelines; audio/voice last.

## 7. Definition of 'matches a leading coding agent'

No unsupported equivalence claim. Select a private benchmark with 30–100 representative user projects in categories above; compare end-to-end artifact correctness and manual-intervention count against available frontier agent workflows under identical requirements, tools and time budgets. Record reproducible runs, failed builds, reasons for failures and security issues. Optimize completed projects per hour/watt/GB, not number of downloaded skill files. A target is a *measured* result, not a model-name slogan.

## 8. What this package actually changes

Add five new release files across `mio/`, `scripts/`, `tests/`, and `docs/`. Its registry is a **safe planning component only**, not yet wired into live model routing. No GPU allocation, model download, automatic third-party skill installation, new Vercel APIs, auto-repair behavior change, or modification of `MASTER_PLAN.md`/`AGENTS.md`. The installed `mio/resource_policy.py` remains an unrelated unpublished work item; do not overwrite it.
