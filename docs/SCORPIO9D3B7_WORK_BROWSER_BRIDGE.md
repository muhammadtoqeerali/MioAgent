# SCORPIO9D3B7 — Owner-approved Work browser bridge (staged)

## Goal

Connect the already verified SCORPIO9D3B6 public HTTPS grant broker to a specific
MioAgent Work run without giving ordinary language-model prompts the authority
to grant internet access. This is an **API and Work-worker integration** only;
production deployment and everyday Chat live-research routing are separate phases.

## Interfaces (after separately approved API and worker activation)

All routes use the existing Work API `require_token` dependency.

1. `POST /api/work/projects/{project_id}/browser-proposals` with
   `{"prompt":"Read the official Python documentation", "url":"https://www.python.org/"}`.
   Response is `needs_review`/`browser_proposed`; no grant is issued.
2. `GET /api/work/runs/{run_id}/browser-proposal` reads the immutable scoped URL.
3. `POST /api/work/runs/{run_id}/browser-decision` with `{"approve":true}`
   queues exactly one owner-approved Work action. `{"approve":false}` denies it.
4. The independent worker handles `browser_queued` before LLM reasoning and
   before any standard task tools. It atomically consumes and clears the Work
   token, then invokes SCORPIO9D3B6's independently single-use broker.
5. The existing public-HTTPS client fetches bounded, public-only evidence and
   Playwright checks its inert rendering inside network-disabled Bubblewrap.
   Completion records source URL, page and render hashes, and Work audit events.

No grant is issued from Chat, search results, downloaded content, or model text.
This phase does not execute arbitrary HTML scripts from websites, download
files, grant persistent networking, provide host shell, or install packages.

## Lifecycle and denial behavior

- User creates a proposal → no Work queue or permission changes.
- Reject → recorded as failed, no broker token.
- Approve → a five-minute-maximum B6 grant is issued; a Work binding becomes
  queued only after successful issuance, and only for the exact project/run/URL.
- The worker atomically clears its Work token *before* calling the broker,
  which itself consumes the grant *before* the network fetch.
- Expired, interrupted, mismatched, or spent grants cannot be silently retried.
  The user creates and approves a new proposal.
- The Work run is marked answered only when the B6 broker verifies an isolated
  rendering. A verified render is not presented as proof of document facts.

## Acceptance

The guarded source release enforces pinned Git head, protected worktree hashes,
source/package integrity, workstation Ruff and Python tests, TypeScript check,
existing isolated real-worker acceptance, one live HTTPS page through a freshly
created **temporary isolated Work database** and offline Playwright, unchanged
service identities, and one targeted Git publication.

This source release intentionally **does not restart or activate** the API,
dashboard, Work worker, or ComfyUI. Production activation requires a separate
owner-approved maintenance step including a backup of the private Work SQLite,
API/worker endpoint smoke tests, and a controlled rollback plan. The simplified
Approve/Reject UI and automatic topic-to-URL proposal generation are not part
of the source-only release; neither is a fix to `/chat`'s `assistant/ask` path.
