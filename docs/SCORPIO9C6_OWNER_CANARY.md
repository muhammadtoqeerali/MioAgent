# SCORPIO9C6 — Owner-driven live Work canary, opt-in only

Baseline: accepted SCORPIO9C5 commit `05793ce68b0afab1af1c22e5ab7509ba1519585b`.

## What this release adds

A guarded local CLI that can (a) **read-only** check whether the existing native Work DB is ready for an optional synthetic canary, (b) **only with separate, explicit interactive-terminal approval**, make a single *draft* canary project/plan, synthetic plaintext file and exact-step grant (30-minute limit), and (c) read-only verify the real managed worker's persistent run/step/grant/event evidence after an independently reviewed Supervisor plan approval. The phase publish controller never calls the mutating `prepare` action.

No new worker executor, HTTP write endpoint, permissions, model tool, shell tool, external skills/MCP, or self-modification. The dashboard, API, independent worker and ComfyUI need no restart. User datasets and existing projects are not scanned or copied.

## Release acceptance and manual opt-in

The release controller verifies the exact baseline, owner dirty paths, preinstall Ruff, focused tests, full pytest regression, Next.js TypeScript, and the accepted 9C5 isolated worker/Bubblewrap acceptance before selective commit and non-force push. It then invokes **only**:

```bash
PY="$HOME/.cache/mioagent/phase1-venv/bin/python"
"$PY" -B -m mio.scorpio9c6_console readiness
```

This is read-only and does not create a Work DB. If you decide to run a *real* owner-approved canary, first check `readiness` and confirm no active runs/plans and no earlier labeled canary. Then, from an **interactive local terminal**, explicitly run:

```bash
"$PY" -B -m mio.scorpio9c6_console prepare \
  --approval 'APPROVE SCORPIO9C6 CREATE SYNTHETIC LIVE DRAFT NO AUTO APPROVAL'
```

This opt-in step **does modify production Work data**: it first makes a consistent owner-private SQLite backup under `/var/tmp/mioagent-native-UID/scorpio9c6-canary-backups/`, then creates one clearly labeled native Work project, an owner-private synthetic text file, an unapproved draft supervisor plan, and one expiring single-use grant. If a step fails after project creation, partial labeled data may remain; no automatic DB restore or destructive cleanup is attempted, and duplicate preparation is denied.

Copy `project_id` and `plan_id` from the JSON result. Open `http://127.0.0.1:3000/supervisor`, **review the exact one-step draft**, and, *only if you choose*, click the existing **Approve and run** action before the 30-minute grant expires. If you do not approve, the draft performs no tool operation. There is no model-generated consent or automatic plan approval.

Then check result:

```bash
"$PY" -B -m mio.scorpio9c6_console verify \
  --project PROJECT_ID --plan PLAN_ID
```

An accepted successful result is `"outcome": "passed_real_managed_worker"`, requiring the exact saved digest, a completed supervisor step, one consumed grant, matching run status, and independently recorded claimed/verified audit events. Otherwise it reports pending/owner-attention or rejects inconsistent evidence. Neither the CLI `readiness` nor `verify` changes Work state.

## Limits and safety

- Synthetic data only: exactly `scorpio9c6_canary.txt` and a fixed bundled string; no user-selected file paths, network reads or secrets. Filename/path traversal and symlinks are never accepted from CLI arguments.
- **Two separate owner decisions:** interactive `prepare` creates a draft; dashboard plan approval triggers the already accepted 9C4 worker path. Release installation never constitutes approval for a production Work task.
- The canary creates persistent, labeled project/grant/run metadata; it is *not* silently erased. Use the existing project lifecycle interfaces for owner-directed archival/removal after reviewing results. Do not blindly delete database rows or backups.
- Authorization remains owner-UID/terminal-scoped, not cryptographic strong session identity. No claim of protection against malicious same-UID processes or compromised Linux kernel.
- No automatic retries or grant renewal; if the approval window expires, the operator sees an owner-review result. Do not silently replace the grant.
