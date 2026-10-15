# MioAgent Master Plan

- **Plan version:** 1.0
- **Status:** ADOPTED / BASELINE
- **Date adopted:** 2026-10-15
- **Repository:** https://github.com/muhammadtoqeerali/MioAgent
- **Primary workstation location:** `/mnt/hdd16T/ToqeerHomeBackup/toqeer/MioAgent/`

## Purpose and non-negotiable goals

Build MioAgent as a locally hosted, always-available, secure personal AI engineering assistant controlled by voice, written instructions, and a real-time dashboard. It must coordinate difficult tasks such as software development, scientific research, documentation, controlled browser interaction, computer operation, and project workflows while retaining meaningful long-term context.

Architecture must support multiple specialized workers with model-provider independence, local/cloud routing, durable execution, observability, scoped access permissions, GitHub integration, and a governed continuous-improvement cycle.

Always-on means event-driven availability and recoverable background work; it does **not** mean unlimited computation or continuous idle token generation. Provider quotas, token windows, operating costs, GPU memory, and model limitations are real constraints to optimize around, never bypass.

## Development conventions — binding rules

1. Implement **cohesive, substantial, end-to-end feature batches**, with full files instead of a sequence of tiny patches wherever practical.
2. Each useful milestone follows **implement → validate → test → document → Git commit/push**; untested changes should not be described as complete.
3. Workstation code is the authoritative deployment copy. Publish to GitHub only after testing against this workstation and reviewing the change set. Do not publish credentials, private content, local memories, or unauthorized datasets.
4. Keep master plan scope fixed as baseline; modifications require an Architecture Decision Record (ADR), including rationale and impact.
5. Every dashboard claim must reflect actual service state. No simulated agent status should be shown as live production operation.
6. Permissions must be enforced by backend tools, not prompt instructions alone. Explicit approval for destructive, sensitive, external, or costly actions.
7. Models, voice engines, memory stores, worker frameworks and frontends must be replaceable without rewriting orchestration logic.

## Planned architecture

- **User interface:** Next.js, React, TypeScript, Tailwind CSS, later optional native desktop app. Live tasks, process status, approvals, logs, terminal/browser preview, system load, model usage, costs, outcomes, emergency stop.
- **Speech:** push-to-talk first, local transcription, local speech synthesis, optional cloud services, later opt-in wake word. User-visible microphone state.
- **Orchestration:** Python + FastAPI; supervisor for task understanding, planning, decomposition, delegation, conflict resolution and verification. LangGraph candidate for state graphs; Temporal candidate for long-lived workflow orchestration once needed.
- **Workers:** coding, debugger, research, data science, writing, browser, computer, GitHub, reviewer, memory, and learning roles. Logical roles may share model instances; dedicated processes only where useful.
- **Tools:** allowlisted workspace file access, isolated shell/container, code testing, Git, GitHub, browser Playwright, official provider APIs and MCP; each enforced by resource/action/duration policy.
- **Models:** local GPU models through Ollama or vLLM, hosted models via vendor adapters or LiteLLM, automatic selection subject to user-defined quotas and policy. Caching, checkpointing, retrieval, and failure fallback.
- **Persistence:** PostgreSQL for tasks, runs, events, approvals, audit metadata; pgvector for semantic retrieval; local file volumes for artifacts; optional Redis for messaging/caching.
- **Learning:** verified ingestion of documentation, papers, releases and approved sources; persistent searchable knowledge; task retrospectives; offline benchmarks; sandboxed experimental improvements; human approval before production self-updates.
- **Operations:** Docker Compose local-first deployment; monitoring through structured logs, OpenTelemetry/Grafana as warranted; restart recovery; work queues; priority, cancellation, cost caps and budget controls.

## Seven planned development phases

### P1 — Foundation and workstation baseline

Inventory host/hardware/filesystem/software, establish project structure and version control, initialize Docker stack, backend/dashboard health checks, basic persisted task queue, unit/integration tests, clear docs and safety defaults.

**Acceptance:** reproducible setup with real API and frontend, locally verified tests, initial GitHub baseline, no publicly exposed management endpoints.

### P2 — Intelligence, orchestration and memory

Model gateway, at least one local/cloud provider, task planner and supervisor, structured prompts/tool contracts, retrieval memory, checkpoint persistence, and context budgeting.

**Acceptance:** a genuine multi-step AI text task survives a restart and reports reliable status/outputs.

### P3 — Voice and professional control dashboard

Speech-to-text, text-to-speech, push-to-talk, optional wake word, streaming events, runtime monitoring, controls, approvals, real hardware metrics and polished UX.

**Acceptance:** user can speak a task, track real progress and hear a response; no microphone recording without explicit permission.

### P4 — Coding, browser and computer tools

Sandboxed terminal, scoped filesystem tools, Playwright, source control workflows, code generation, tests, debugger, artifact packaging, approvals and rollback.

**Acceptance:** safely build and test a small project inside an isolated workspace; changes reviewed and pushed only after authorization.

### P5 — Specialist agent collaboration

Research, coding, reviewer, writing and data-science delegation, task dependencies, parallel work, citation/source tracking, consolidated reports and verification.

**Acceptance:** complete a bounded research-and-coding workflow with independently checked results.

### P6 — Always-on operation and controlled learning

Durable schedules, restart recovery, periodic source research, memory indexing, benchmark evaluations, change proposals, cost/performance trend monitoring.

**Acceptance:** recover long-running tasks, ingest a trusted update, generate a testable improvement proposal without silently changing production code.

### P7 — Hardening and deployment optimization

Threat modeling, origin/auth controls, secret isolation, audit logs, fault-injection tests, latency and hardware profiling, operating runbooks, backup/restore, reliability metrics and release quality gates.

**Acceptance:** a security-reviewed, documented, reproducible workstation deployment with measurable reliability and clear failure recovery.

## Security boundaries

Never implement a hidden unrestricted administrator agent. Remote management is off by default. Untrusted websites, documents, repositories, tool outputs and model responses cannot override user authorization. Use explicit resource-scoped grants, test before deploying improvements, and provide a stop mechanism that interrupts work at the tool execution layer.

## Known machine constraints

Two RTX 4090 cards have separate 24 GiB VRAM allocations; total capacity does not imply unified 48 GiB memory. The 17 TB filesystem is mounted and currently reported with root ownership and permissive mode bits; inspect mount semantics prior to permission repairs. Use actual available system RAM rather than 'free' RAM alone.

## Change policy

Keep this baseline unchanged except for explicit versioned revisions (1.1, 2.0 etc.) accompanied by ADRs. Implementation detail changes should be documented in ADRs and release notes without rewriting project objectives. See `docs/decisions/0001-adopt-master-plan.md`.
