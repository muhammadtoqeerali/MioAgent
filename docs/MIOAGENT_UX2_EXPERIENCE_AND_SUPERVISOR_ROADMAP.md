# MioAgent UX2 — Chat / Projects / Work / Control Room

**Release type:** preview-only frontend reorganization on the published e3c9d0c v0.4K backend and the previously installed UX1 preview. No GitHub publication until user acceptance.

## Main product contract

The navigation must have only four primary destinations. There must be no navigation to old `/studio`, `/assistant`, `/intelligence`, `/projects`, `/work` or command-center pages. Keep those old routes installed temporarily as fallbacks; the homepage and previous `/workspace` URL redirect to Chat.

| Destination | User intent | Current service wiring | Proven vs future |
| --- | --- | --- | --- |
| Chat (`/chat`) | Normal new conversations with history | Existing `/api/assistant/ask`, conversations and tasks; optional Studio image job | Local persistent text conversations; image rendering private, but not linked to persistent conversation yet |
| Projects (`/projects-space`) | Ongoing topical discussion with files and instructions | `/api/work/projects`, approved `/memory`, Studio upload then `/files`, `/runs` | Persists project instructions, explicit memory, files, response history. Prior run text is **not** automatically included in next run's model context yet; this limitation is disclosed. Instructions are creation-time and not editable yet. |
| Work (`/work-mode`) | Owner-delegated, bounded supported task, explicit goal/acceptance and preflight | Project titles marked `Work · ` in current Work SQLite and Work run API. Work jobs start as asyncio tasks inside managed FastAPI. | API process can continue without browser; no server-restart auto-resume, no unrestricted computer actions, no durable separate agent daemon or dynamic permission-grant system. UI prevents starting explicitly computer-bound task profiles. |
| Control Room (`/control-room`) | See supervisor/role office and real audit timeline | v0.4L UX1 event-driven Control Room | Representation of saved phases; no simulated independent agents. `model.review_unavailable` remains visible. |

The Work/Projects separation is a UI convention in this preview (title prefix) rather than a security boundary; backend isolation is mandatory before implementing permissioned autonomous engineering.

## Immediate acceptance

1. Start at `/` and reach `/chat` rather than legacy overview; only four primary nav choices.
2. Chat > New chat > ask a local model question > task reaches completed and saved conversation appears after refresh.
3. Chat > Image > request an image > get real ComfyUI PNG if configured/running; show an actionable error otherwise.
4. Projects > create project with instructions > upload txt/MD/PDF within limits > link files > add owner-approved memory > ask task and see saved reply with sources and Markdown. Refresh and confirm persisted.
5. Work > new > select computer task and observe it cannot start (no deceptive execution); select bounded research > approve bounded access > start and see queued / model / review / final events; close browser, reconnect, confirm state persists.
6. Control Room > select the saved Work delegation and confirm status accurately reflects each recorded phase or reviewer failure.
7. Check `/chat`, `/projects-space`, `/work-mode`, `/control-room`, `/workspace` redirect, and private Next.js API proxy behind an SSH tunnel. Confirm unsupported functionality is not advertised as active.
8. Preserve 11 unrelated untracked files, local Ollama models, active SQLite state, ComfyUI, service ownership, Windows SSH port-forward. No auto Git commit/push.

## Follow-on backend phases (prioritized)

### B1: Real project discussion continuity and memory editing

- Add persisted project message threads or securely bounded prior-turn context server-side; user follow-up should reference previous turns without including the entire history in an untrusted prompt.
- Add explicit project-instructions editing with versions and optimistic concurrency (`expected_revision`). Bound project memories with owner view/edit/revoke; file library index and retrieval citations.
- Separate `chat`/`project`/`delegation` identities as immutable, server-side types in a schema migration (not title prefixes).

### B2: Persistent supervisor service

- Implement a separate managed service supervised on Ubuntu, not `asyncio.create_task` tied to FastAPI lifespan. Use durable SQLite/Postgres job table: `submitted`, `needs_requirements`, `awaiting_approval`, `ready`, `running`, `blocked`, `needs_review`, `completed`, `failed`, `canceled`, `interrupted`.
- Transactional queue and leases, heartbeat, checkpoints, budget/deadline, bounded repair attempts, idempotency keys and run recovery. Per-run persisted plan and acceptance contract. Service restarts resume only safe and idempotent steps; non-idempotent steps pause for owner review.
- Supervisor plans/delegates on explicit tool capability manifests. Do not claim that a system prompt grants tools. Separate planner, executor, verifier, reviewer and artifact delivery evidence.
- Approval API presents requested exact local folder, action, command/domain and expiration; approvals are scoped to an immutable run and revocable. Reject prompts and retrieved pages that attempt privilege escalation. No inherited raw sudo, global shell or workspace access.
- Event-driven Control Room and notifications read actual worker state, not fake office animations. Distinguish reviewer unavailable from verified acceptance.

### B3: Real tool use under enforced permissions

- Folder operations under approved roots via canonical descriptor-based path resolution, symlink protection and backup/patch preview.
- Bubblewrap/namespace isolated subprocess tool with no host write/network by default, enforce CPU/RAM/process/time/disk quotas and cancellability. Demonstrate multi-file repository build/test/review and safe commit proposals.
- Playwright separate Chromium context, private browser profile, fixed domain allowlist and SSRF prevention, per-action audit; ask owner approval before credentials, logins, submission, upload, payment or irreversible actions.
- Skills/MCP with schema/pin/trust/grant policy and audit. Avoid arbitrary third-party instruction execution.

### B4: Local ComfyUI integration and art/document polish

- Managed ComfyUI status/start/stop service wrapper with explicit owner opt-in, ownership checks, GPU index awareness, no surprise downloads; health/error/queue panels surfaced through the same Chat interface.
- Persist image job refs in the appropriate chat/project, gallery, attachment inspection, artifact viewer and file editing library.
- Refresh UX: keyboard shortcuts, streaming, long-run notifications, accessibility, mobile layout; robust markdown and citation panels; high-quality local image workflow only after model/disk/VRAM benchmarks and explicit license/download approval.

## Publication gate

One allowlisted release at a time: archive SHA-256 + internal manifest, strict baseline Git SHA check, protected untracked state, Ruff/full Python regression, TypeScript and Next.js production build, service restart/smoke, real user browser acceptance, *then* commit allowlisted files from workstation and record the new SHA. Never claim a tool executes unless evidence actually exists.
