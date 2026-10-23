# SCORPIO7A — Scorpio Control Room visual and owner-review integration

## Purpose

**Scorpio** is the dashboard-facing platform name and scorpion visual identity.
This phase intentionally retains the MioAgent repository, module, SQLite store,
API routes, existing tokens and running native system names. Renaming their
underlying identifiers is NOT authorized; it would risk breaking a live system.

The old Control Room showed real events but could only report `needs_review`.
Its status never represented a pending backend permission decision. This release
adds a substantial owner-facing Control Room and actionable bounded next steps:

- Project-scoped real Work queue, status filter, automatically refreshed run audit
  events, recorded output, error detail, source evidence and API capability report.
- A persistent navigation path back to all project assignments and sealed reviews.
- When an existing Work run is terminal, the owner may enter feedback, choose a
  bounded task or a read-only source inspection, explicitly approve the exact
  next action and submit **one NEW Work run** via the authenticated API.
- The API enforces a single queued/running Work task; source inspection needs the
  already-enabled dual flag, explicit approval and a server-side allowlist.
- No claims that a `needs_review` task is merely a citation failure. The UI says
  when a prior run is unverified/failed/interrupted and shows its actual events.

## Important limitations

The existing Work database marks `needs_review`, `answered`, `failed`, and
`interrupted` as terminal states. There is no safe checkpointed in-place resume.
The new UI is truthful: approval **creates a fresh follow-up**, with prior run ID,
truncated prior prompt and new owner feedback in the next prompt. The supervisor
can interpret that context but cannot inherit prior in-memory tool state.

Clicking **Not now** closes the form locally; it is not a backend denial record.
This release does not implement a durable approval ledger, per-tool approval
requests, permissions granting, automatic continuing agents, or workstation control.
No simulated CPU/GPU statistics or fictitious agent activity are shown.

The earlier image concept is illustrative only, NOT measured production data.

## Deployment gates

Guarded no-sudo source installation is separate from dashboard deployment. The
installer refuses unexpected Git status, unexpected HEAD/branch, changed source
blobs, symlinks and non-exact SHA-256 source. It runs TypeScript typecheck, Python
source-contract tests, and full native-memory regression in Bubblewrap. It MUST
NOT restart the dashboard, API, worker or ComfyUI, submit live Work tasks, alter
SQLite/credential storage, commit, stage or push code.

The existing Next.js service uses a built artifact. Install success does not
change what the browser currently sees. First accept tests and selectively
publish source, THEN authorize a separate dashboard build/restart with health
verification and rollback. API/Work worker do not need restarting for this UI
phase. Read-only Work inspection remains process-flag-gated after future restarts.

## Follow-on implementation roadmap

- **SCORPIO7B:** safe targeted dashboard build, static integrity, verified
  service restart; browser smoke test of project/task selection and owner
  follow-up approval. Preserve ComfyUI, API, worker, and all active Work tasks.
- **SCORPIO7C:** backend durable owner approval requests with explicit typed
  capabilities, source/path/scope/time bounds, deny/revoke, full audit trail,
  expiration, one-shot consumption, and atomic owner authorization checks. Never
  infer approval from model-generated text. No broad host grants on NTFS/FUSE.
- **SCORPIO7D:** persisted supervisor DAG and task-specific checkpoints;
  interrupted jobs return to review, approval creates one bounded continuation,
  with rate/budget limits, safe retries, human escalation and delivery receipts.
- **SCORPIO7E:** isolated per-job Python/engineering workspaces, diff preview,
  tested artifact release, no silent repository edits; then permission-scoped
  computer/browser tools after separate isolation and security acceptance.

## User-visible testing

After a separately authorized dashboard deployment, go to
`http://127.0.0.1:3000/control-room` and select an existing Work project and run.
Use the **Give feedback / approve next step** section to submit a new bounded
follow-up or read-only inspection. A production run affects the live Work queue;
installation/tests themselves create none.
