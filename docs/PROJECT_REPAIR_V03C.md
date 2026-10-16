# MioAgent v0.3C — Local-only repair proposals from failed sandbox tests

**Developer-preview scope:** One bounded model-generated proposal per approved project, not autonomous project completion.

## Actual workflow

1. Generate and approve a project containing Python `unittest` tests.
2. Approve Bubblewrap test execution. The newest verification must have `status=completed`, `outcome=failed`, `executed=true`, and `passed=false`; a passing project cannot request a repair.
3. Explicitly request a repair proposal: `POST /api/projects/{id}/repair` with `{"approved":true}`. The single durable worker calls the configured **local** model (cloud disabled) with bounded context: requirements, source, immutable tests, and failed-test log.
4. The model may replace **one or two existing non-test Python files**. All other source bytes and every `test_*.py` file are preserved. No new files, changes to tests, command execution, network access or automatic edits.
5. Review `GET /api/projects/{id}/repair`. A proposal is static validation only; it has **not** been executed or verified.
6. Explicitly create a reviewable revision: `POST /api/projects/{id}/repair/use` with `{"approved":true}`. This creates a **new `Project` in `review`**, preserving the original workspace.
7. Review all files again, then use the existing source approval, sandbox verification, and immutable artifact path for the new revision.

One proposal per parent project and one promotion per proposal prevent repeated automatic looping. Creating successive reviewed revision projects is possible, with fresh human approval each time. No background self-modification or model-driven Git push.

## Security and budgets

- Existing localhost bearer token and the separate Project Mode/sandbox flags remain prerequisites.
- Each AI call uses only the already configured local Ollama model; maximum output is limited by the model gateway to 2,048 tokens. No new GPUs, V100 usage, or paid cloud calls.
- Source/test context at most 14,000 characters; failing-test log at most 4,500 chars; model response at most 26,000 bytes; up to two replacement source files, each at most 16 KiB, subject to overall Project Mode 64 KiB budget.
- File contents, requirements, and test output are *untrusted text*, including possible prompt injection. All proposed content is validated again after generation, and tests are hash-checked unchanged before promotion. Original artifacts are verified against approved byte hashes before the model call and promotion.
- On interruption, a queued/running proposal may repeat a free local-model call; no source files are written by the proposal worker.
- A `review` revision has no workspace on disk until explicit approval, and is not executed until a *second* independent sandbox approval.
- Vercel API proxy remains deliberately disabled on Vercel; only the frontend changes online. Workstation backend and private tokens stay loopback-only.
- Persistent SQLite and project artifacts remain under `/var/tmp` pending a durable ext4 migration, backup strategy and quota enforcement.

## Release validation

Automated tests cover failure eligibility, anonymous access, stale/no-op/test-file modification rejection, local-only model routing, immutable approved originals, one-time proposal promotion and review-only child projects. Workstation release additionally requires full pytest, Ruff (in repo context), Next.js typecheck/build, live Bubblewrap probe, native runtime smoke, Git publication with explicit file allowlist and no prompt. No project code is executed during installer tests.

## Out of scope

No unconditional automation, trusted execution outside Bubblewrap, runtime package installations, frontend remote backend bridge, browser interaction, adversarial-security guarantee or frontier-quality performance claim. This is the **first correction-proposal stage**; automatic multi-iteration repair will require a stronger executor, durable checkpoints and measured benchmarks.
