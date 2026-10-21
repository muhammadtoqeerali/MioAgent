# MioAgent Backend B1 — first functional reliability phase

**Baseline:** published UX2.1 `7d53555389ed766b92e84bb63fb5fe534acff052` (which includes v0.4K). B1 itself remains uncommitted until its runtime acceptance tests succeed.

## Scope implemented in B1

1. **Project conversation continuity:** the last five completed turns from the *same project* are supplied to the local Work model in chronological order, bounded to 4,400 characters. User-authored instructions and manually approved memories remain separate. Never make project files or prior model answers into permissions. Distinct delegated Work assignments do not inherit other assignments' answers.
2. **Dedicated persistent Work worker:** new Work requests remain in owner-private SQLite; a dedicated managed worker executes `mio.work_agent.execute`, independent of FastAPI request and browser lifecycle. API restarts no longer mark actively worker-owned tasks interrupted; the worker keeps running if only the API/dashboard stop. If the worker itself dies, its old running task is explicitly marked `interrupted` on the next worker start; queued tasks are retained. There is no unsafe automatic replay of possibly half-completed tool actions.
3. **Managed installed ComfyUI backend:** if a healthy ComfyUI instance is already available on 127.0.0.1:8188, reuse it. Otherwise, start the *existing* ComfyUI virtualenv on GPU index 1, never download anything, never kill unidentified processes, and report actual readiness. Image output remains backed by the installed SD1.5 checkpoint until an owner-approved, measured upgrade.
4. **Operational visibility:** `scripts/native_runtime.py start/status` invokes/reports managers; logs are under the existing owner-private runtime. The public UX2 routes and model fleet policy are preserved, no new browser/host shell/file grants are added.

## Limitations requiring honest UI labels

- B1 worker survives browser closure and an API/dashboard restart. It is a separate OS process, **not yet systemd user service with boot-time autorestart**. It cannot survive a whole computer poweroff. Its active job cannot be safely replayed from an arbitrary halfway state; failure is recorded as interrupted.
- B1 works on the *bounded* Work skills: public research metadata/snippets, owner-linked documents, local model drafting/review. No arbitrary terminal, browser, or folder authority; no unchecked tool plugins.
- Conversations summarize only the last five saved project turns, not unlimited chat transcripts. Long-term memory is explicit opt-in. The older `/chat` global assistant still uses its own conversation store.
- B1 does not improve the SD1.5 checkpoint's underlying image quality. Readiness first, then licensed quality benchmark and workflow upgrade with the owner's download approval.

## Acceptance gates for B1 before commit

- All 8 new offline tests, Ruff, the complete Python suite and Next TypeScript check pass on Ubuntu.
- Check process identities: API, Next.js, independent Work worker and ComfyUI, without killing external listeners.
- Run two actual Project turns where the second references an uncommon detail only in the first reply. Verify the answer includes correct context and a `context.history` event; no cross-project leak.
- Start one genuinely bounded Work research/writing job, close the browser or restart only API/dashboard, then confirm the worker continues and produces persisted evidence and a downloadable artifact. Never kill the worker during this test.
- From `/chat`, request one real image. Verify ComfyUI readiness and a valid PNG; if not ready, inspect `logs/image-backend.log` and save the failure without claiming readiness.
- Verify previous local model fleet inventory/digests, no cloud inference, ComfyUI checkpoints, runtime private DBs and eleven unrelated untracked files untouched.
- Only after the owner submits successful logs and browser confirmation: exact allowlisted B1 commit/push from Ubuntu. No auto-commit in this package.

## Next ordered, substantial phases

**B2 — durable supervisor contracts + permissions:** explicit owner-scoped task contracts, approval-before-execution, workspace allowlists with symlink/path traversal barriers, step-level checkpoints, cancellation, per-tool ledger, process-resource caps, Bubblewrap isolation of commands. Dedicated user `systemd` service where supported. Make the Work UI display exact permissions and supervisor states.

**B3 — practical developer tools:** repo inventory/edit/search/patch, sandboxed code runs and tests, approved Playwright browser tabs/profiles with network/SSRF restrictions, reproducible build/test/review loops, source diff preview, owner-approved application. Demonstrate a real multi-file project fixed and accepted by tests.

**B4 — skills and MCP:** versioned schemas, trust/permissions, isolated credentials, explicit enable/disable, audit and revocation; untrusted external instructions never expand access.

**B5 — image and model quality:** benchmark Ollama role fleet on tasks and actual GPU memory/time, recorded successes and failure rates. Upgrade ComfyUI to a modern licensed diffusion workflow only after owner authorizes storage/model downloads. Candidate: FLUX.1 schnell (Apache 2.0) with appropriate quantization/workflow; dev has different commercial restrictions. Optimize GPU1/GPU2 occupancy; preview, retries, image editing/variations and gallery; do not promise parity with proprietary generators.

**B6 — integrated autonomous completion:** supervisor plans, bounded delegated specialists, task-local memory, evidence, independent review, durable retries and task resumption with explicit approval, finished artifacts and source-controlled handoff. Prove complex end-to-end acceptance rather than status-button demos.
