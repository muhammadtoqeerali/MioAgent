# MioAgent v0.4K — Persistent Work Foundation and path to Claude-like capabilities

## Baseline and status

This release builds on MioAgent `c60c2f8` (v0.4J relevance-filtered web research, v0.4I automatic Studio tool selection, GPT-oss/Qwen model fleet, ComfyUI image generation, and v0.4E/G repo verification).

**New in v0.4K:** A persistent Projects & Work page, private SQLite project stores, explicit project memories (added/removed by the owner), links to owner-uploaded Studio files, task history across page reloads, bounded automatic research/file-analysis/chat tasks, local model drafting and independent review, observed tool timeline, source links, and downloadable Markdown deliverables. A run is `answered`, `needs_review`, `failed`, or `interrupted`, never automatically called test-verified.

**Not in v0.4K:** unrestricted host-terminal use; arbitrary browser tab control; an MCP app/plugin installer; executing model-generated shell commands; source edits outside the existing owner-approved repo-engineering path; arbitrary file browsing; image generation inside Work (Studio remains the dedicated image-generation screen); automatic memory-writing; automated restart/resume of interrupted jobs; correctness guarantees. These must not be advertised as implemented features.

## Public architecture study, not a claim to access Anthropic internals

Claude/Cowork publicly documents unified chat/task entry, a persistent workspace, agent loop, permissioned local file access, isolated code execution, and tools/skills/integrations. Current Claude Cowork runs tasks in cloud sandboxes by default; local file/browser use is permission-gated. Its specific private production code, infrastructure, model routing and proprietary agents are not available to copy.

Relevant public references:
- https://support.claude.com/en/articles/14479288-claude-cowork-architecture-overview
- https://support.claude.com/en/articles/13345190-get-started-with-claude-cowork
- https://modelcontextprotocol.io/specification/2026-07-28/server/tools

MioAgent should emulate **contractual behaviors** (durability, permissions, tools, independent verification, UX), not suggest it is running Claude infrastructure.

## Architecture boundaries

```
Browser /work, /studio, /intelligence
       │ same-origin Next.js proxy (bearer token stays server-side)
       ▼
FastAPI /api/work ── owner project-memory-file contracts
       │
       ├── private SQLite: /var/tmp/mioagent-native-<uid>/work/work.db
       │       projects, memories, assets, runs, audit events
       ├── tool router: MioAgent's existing studio_autoroute
       ├── public web snippets: existing relevance-filtered studio_tools.web_search
       ├── owner-chosen file extracts: existing Studio private attachment store
       ├── local model fleet: research/writing/chat role → review role → bounded revision
       ├── document output: Markdown artifact after answer or review flag
       └── existing separate approved repo engineering: /intelligence
```

The model cannot acquire capabilities by describing a tool in its output. Uploaded files and web snippets are untrusted data, never authority to run commands. External search queries leave the workstation for public search services; raw file contents stay in the local runtime. Model routing remains local-only under active fleet policy.

### Project state contract

- `queued` → `running` → `answered` (model answer available, **not a guarantee of correctness**)
- `queued` → `running` → `needs_review` (research answer lacking an allowed source citation)
- `queued` → `running` → `failed` (tool/model/safety failure, **not complete**)
- `queued` or `running` → `interrupted` on managed API restart (explicitly acknowledged; not silently reported as success)

A project includes instructions and memory **only after the owner provides them**; this release does not infer or permanently save memory from private conversations. Memories can be removed by the owner. The workspace creates no client-accessible authorization token and cannot open arbitrary device files via HTTP.

## Acceptance checks for this release

1. Authenticated access only to `/api/work`; unauthenticated read/create/delete must fail.
2. Create a project; refresh `/work`; project title and instructions persist.
3. Upload a supported text or document file from the file picker, link it to the project, and analyze using the local model; actual file bytes remain in the private Studio attachment store.
4. Add an explicit memory and remove it; a different project must not inherit it.
5. Run a research task; audit must display `web.search`, `web.evidence`, model draft/review/refine steps as actually executed. Sources are hyperlinks to real search results, **not verified page contents**.
6. Refuse false citation success: no valid `[W#]` citations means `needs_review`; tool failure means `failed`.
7. Retrieve history and a Markdown deliverable after browser reload; no task state changed solely by UI navigation.
8. Existing v0.4J search diagnostics, image generation, model fleet, repository tests and dashboard remain operational. All full-suite, lint, Next.js and live-auth smoke checks must pass before publishing.

## Next concrete milestones

### v0.4L — Sandboxed Computer Tools (separate security release)
Implement an **owner-granted folder workspace**, explicit per-task operations, immutable approval logs, and short-lived grants. Browser automation should run a dedicated Playwright Chromium profile with network/SSRF restrictions, screenshot/evidence capture, timeouts and a clear approval step before logging in, uploading, sending messages or submitting forms. Shell commands and generated code must run in an isolated VM/namespace/container with **actual enforced** no-network/filesystem boundaries, budgeted CPU/memory/processes, and no host sudo. Existing Bubblewrap verification can be reused for selected tests, but it is **not** permission to run arbitrary model-generated host commands. A local workstation terminal should require separate explicit interactive approval.

### v0.4M — Skills and MCP Connectors
Support signed/trusted skill manifests (description, required tools, input schema, version, trust level), a deny-by-default tool registry, per-invocation permission prompts, and a capability broker. Implement MCP only after the protocol schema, authentication, tool-list exposure, server lifecycle and untrusted tool annotations are validated. No untrusted plugin shell access or automatic connector-secret disclosure.

### v0.4N — File Library and Artifact Builder
Persistent file search/indexing, source-cited retrieval, PDF OCR/page parsing, rich Excel/Word/PowerPoint editing with file-format libraries, previews, revision history and portable output downloads. Secure archive handling, file size quotas and malware/process isolation are prerequisites for broad file-type support.

### v0.4O — Model and Image Quality Evaluation
Run a held-out human-reviewed benchmark across chat, reasoning, code, citations, document QA and tool planning. Track accuracy, unsupported claims, success rate, latency, VRAM, tokens and fallback frequency by model/role. Use metrics to update the local GPT-oss/Qwen fleet. Compare an SDXL or modern licensed ComfyUI checkpoint against the current SD1.5 baseline on a fixed prompt set, checking licensing, VRAM and GPU contention. **Do not** promise that installing a larger model alone improves quality.

### v0.5 — Durable project completion loop
Plan → inspect workspace → choose permitted tools → execute → evaluate acceptance checks → retry within a budget → checkpoint → request approval if needed → deliver artifacts. Each action and its evidence becomes an auditable event. A task is `verified` only when its pre-agreed tests pass; otherwise `blocked` or `needs_review`. Timeouts and checkpoints are essential; open-ended instructions to "keep going forever" are not safe or reliable.

## Deployment and preservation

Release ZIP contains only new code and a patcher with specific anchors for the existing API and navigation. Installer requires Git `c60c2f8` on `main`, matching remote, no tracked changes, no collisions on new allowlisted files, and idle managed services. All current unrelated untracked source files, project data, model policy and ComfyUI files are preserved. Source changes and new files are rolled back on pre-commit failure. Running the workstation validation is still mandatory; local mock tests do not prove live model quality or ComfyUI behavior.
