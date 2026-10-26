# SCORPIO9D2 — Owner-friendly approve/reject Work UX and source-only textutils prompt

Baseline `3d79af373590af592cd23744c179bd38911213b9`, after accepted D1R2.

## Changes

- The Work assignment composer requires **one goal field**. A short title, basic acceptance criteria, and bounded-vs-engineering task routing are derived deterministically in the dashboard. The user sees the proposed mode and chooses **Approve & start** or **Reject — do nothing**. No extra text boxes, radio buttons, or permission checkbox. Backend still checks explicit `approved=true` for engineering tasks and enforces resource policy.
- The existing Control Room and Work owner-action panel stops turning failed **engineering** jobs into research follow-ups. Only a failed/needs-review engineering run with a recorded validation rejection and the exact pinned textutils prefix **or all four named target functions** offers **Approve one new engineering run**, which carries forward its previous requirements and supplies the pinned textutils prefix when absent, as a newly owner-approved engineering run through the existing Work API. It never resumes, escalates tools, changes the original record, or automatically retries. **Reject** starts no task (client-side dismissal only; not a durable audit record).
- Other terminal runs show their evidence and reject/dismiss action but do not propose unsupported automatic retries. The 'no mode selector' policy does not grant new permission types; unsupported host/browser requests remain blocked.
- Only explicitly prefixed textutils engineering uses a **source-only** concise model system prompt. The accepted D1R2 normalizer handles pure Python and the existing independent 13-test Bubblewrap contract remains the sole success authority. The coding model's raw output is still untrusted. Other engineering prompts retain the original JSON-output contract.

## Caveats and validation

This phase simplifies pre-existing workflows; it is not general unconstrained autonomous engineering or durable agentic approval scheduling. A new goal is still needed when creating a completely new task. Automatic task-type routing is bounded and heuristic; reviewers can reject it rather than granting new tools. Client-side Reject does not persist across a browser reload; no server-side denial audit endpoint is claimed.

The guarded workstation controller checks pinned Git blobs and all eleven protected dirty files, pre-install Python Ruff, the full pytest suite, Next.js typecheck before publication, and isolated real-worker/Bubblewrap verification. A full Next.js production build runs during protected dashboard activation after publication. The dashboard build is staged after Git publication under a separately backed-up `.next` directory and uses only the identity-checked managed dashboard process. If build/restart fails after publication, **no extra commit or reset**; recover deployment only.

No production Work project/run/grant or synthetic canary is created by installation. A separate owner click is required to run engineering again. API and ComfyUI remain unchanged.

## Recovery2 regression migration

Three earlier source-level UI test modules were updated to assert the current **equivalent or stronger permission invariants** rather than require old form text, an editable feedback box, or a research-only retry. The revised tests still require explicit owner click, active-run refusal, authenticated Work API calls, new-run identity, no silent resume, and no host/shell permission surface. Source changes are included in the exact Git allowlist and remain subject to Ruff and full pytest.

Historical four-function failed engineering prompts without the original internal marker propose a *fixed* and visibly bounded textutils contract, not a verbatim replay of arbitrary previous task instructions. New one-goal textutils assignments automatically receive the correct contract marker. No run starts until the owner accepts the proposed scoped task. Reject is local dismissal, not a durable server-side permission revocation.
