# SCORPIO9C3 — Exact-step owner staging, no automatic tool execution

Baseline: SCORPIO9C2 commit `c38780004f148d64fb1e12af58c7e9a231c80269`.

This milestone adds an **owner-terminal-only** way to stage a single-use, offline SHA-256 grant for an exact **draft** Scorpio supervisor step **before** approving its plan. It resolves the race that would occur if the owner tried to grant a tool to a plan already being consumed by the independent Work worker. It does **not** add a worker hook, tool-execution API, Git write tool, browser, shell, MCP execution, remote access, skill installation or self-development rights. External skills remain disabled.

## Safe, explicit lifecycle

1. In a real, existing Work project, place one small reviewed file in the already-provisioned private Linux input directory `/var/tmp/mioagent-native-$(id -u)/tool-inputs/PROJECT_ID/`; the directory and its parents must be real, owned by the user and private (0700), and the input must be a regular owner file at most 1 MiB. Never copy secrets/datasets merely to try the feature.
2. Create a supervisor **draft** containing the exact intended step text `Compute SHA-256 for owner-approved file: sample.txt` (filename changes as appropriate). Leave the plan in `draft` state.
3. From an interactive local owner terminal use the `stage` command with exact project, plan, step IDs and filename. It saves a per-step binding, a content/file-identity-scoped expiring grant and an audit record in the **existing** native Work SQLite. Issuance has a maximum lifetime of 30 minutes and is blocked if the draft/step/project/resource does not match. No model output or bearer-token API is allowed to call it.
4. Read the bindings with `bindings`. When the grant is staged but the plan is still a draft, SCORPIO9C1's existing executor **denies** it. Optionally approve the plan through the existing owner approval interface. SCORPIO9C3 has no worker action: the unchanged worker will process the step as an ordinary Work task. This is a deliberate limitation; **do not interpret its result as a tool digest**.
5. `check-queued` is a **non-executing policy preview** for a specific Work run. It verifies run/project/plan/step, queued state, exact file-name prompt, tool class, UID, grant expiry, consumed/revoked flags and archive status. It neither consumes a grant nor executes Bubblewrap. Future worker integration must revalidate content and file identity and atomically consume the grant at execution time, then report verified run state. Do **not** rely on a standalone preview as permission to execute.
6. Revoke through the pre-existing `mio.scorpio9c_console revoke --grant GRANT_ID` from the interactive owner terminal. Expired/revoked/consumed grants deny tool execution.

Run commands using the installed native Python venv from the project directory:

```bash
PY="$HOME/.cache/mioagent/phase1-venv/bin/python"
"$PY" -m mio.scorpio9c3_console stage --project PROJECT_ID --plan PLAN_ID --step STEP_ID --file sample.txt --minutes 15
"$PY" -m mio.scorpio9c3_console bindings --project PROJECT_ID
"$PY" -m mio.scorpio9c3_console check-queued --run RUN_ID
"$PY" -m mio.scorpio9c_console revoke --grant GRANT_ID
```

No new Work project, production run, database or input file is automatically created by the release. Tests run on isolated private fixtures. No production service restart is required. All eleven unrelated worktree files, dashboard, worker, API and ComfyUI remain unchanged.

### Outstanding boundaries before worker activation

A later separately approved release must add a worker-owned execution gate, protect against replay and binding races at the actual consumption transaction, propagate `answered`/`needs_review` to the existing sequential plan, enforce sandbox/FD/owner/file checks at the action boundary, ensure failed tool calls cannot fall back to model text, and verify service restart/rollback and live Work end-to-end. The grant/event inventory API from 9C2 remains **read-only** and its `worker_execution=disabled` statement remains true.
