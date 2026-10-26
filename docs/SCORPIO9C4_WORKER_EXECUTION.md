# SCORPIO9C4 — Exact owner-staged SHA-256 tool execution in the existing Work worker

Base: `fb6f18074768ca3b375a8a38971dd2f445b05c12` (SCORPIO9C3).

## What is enabled

The existing **single, exclusive-lock Work worker** now dispatches one special operation: SHA-256 of a small owner-approved input. No second executor is introduced. An interactive owner terminal stages a grant for one specific **draft supervisor step** using `mio.scorpio9c3_console stage`; the owner must separately approve that plan. On the scheduled step, the worker revalidates the exact Work project, active plan, queued step/run, matching prompt, UID, grant, age, resource directory, inode/device, file size and original digest. The same SQLite transaction marks the grant consumed and the run running **before** launching the already-tested `bwrap` tool. The data comes from the owner-private native Linux tool-inputs area (not the Git checkout). Output is the digest only, recorded in Work run evidence. A denied or failed sandbox ends in `needs_review`; the supervisor halts without reattempting.

## No implicit permissions

* No HTTP endpoint may create grants or run tools. API endpoints remain **read-only inventory**. A model or downloaded skill can never issue grants.
* No general host shell, writable coding, browser automation, network calls, remote APIs, MCP server execution, skill installation, arbitrary host directory reads, or self-modification are enabled.
* Ordinary Work requests follow existing behavior. A digest-looking request without a staged grant is **rejected** rather than answered by a model pretending to have executed a tool.
* Only one 1-MiB-or-smaller owner-controlled file under `/var/tmp/mioagent-native-UID/tool-inputs/PROJECT_ID/` can be read; symlinks and path traversal are denied.
* Revocation/pause can prevent future claims. Already-started 8-second isolated actions cannot be force-cancelled by revoking a consumed grant, but a plan-state/revocation change before results are stored prevents `answered`.
* This is not a general autonomous agent or a security boundary against a malicious same-UID workstation process. SQLite auditing is not tamper-proof. Kernel/namespace isolation must still be independently assessed before accepting broader tools.

## Isolated acceptance and operational consequences

The release controller validates the exact approved files, runs pre-install and installed Ruff, focused tests with real Bubblewrap, full native pytest and TypeScript, preserves the eleven protected owner files, commits only the approved four paths and non-force pushes. After publication, it checks that the Work queue has no running/queued tasks, takes a Linux-private SQLite backup, and identity-checks/restarts **only the Work worker**. The API, dashboard, ComfyUI, Ollama and user datasets remain unchanged. A post-publication activation failure cannot be undone by a Git force-push; the controller attempts a local worker source/service rollback and reports the published commit separately.

No production Work projects or supervisor plans are created for the smoke check; all execution tests use an isolated temporary Linux Work root. An HTTP 200 alone does not establish tool execution.

## Manual owner workflow (after acceptance)

1. Create a real Work project and a draft supervisor plan with one exact step in this form: `Compute SHA-256 for owner-approved file: sample.txt`.
2. Put `sample.txt` in the existing project-specific owner-private tool input folder; no secrets or restricted datasets.
3. From an interactive owner terminal stage the step:

   `python -m mio.scorpio9c3_console stage --project PROJECT_ID --plan PLAN_ID --step STEP_ID --file sample.txt`

4. Inspect the plan and **separately approve** using the existing supervisor dashboard. The existing worker will consume the grant once and save the digest or a denial in Work evidence.

The 15-minute default grant expiry can be shortened or lengthened only within the original 1–30 minute policy. Never silently approve the plan or create input files on behalf of the owner.
