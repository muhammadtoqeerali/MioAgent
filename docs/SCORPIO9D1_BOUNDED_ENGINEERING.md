# SCORPIO9D1 — Owner-approved, sandbox-verified text-utilities engineering

Baseline: SCORPIO9C6 accepted GitHub SHA `e4fb67a144925b47953fc9753defeaf65818d784`; its real managed-worker digest canary returned `passed_real_managed_worker` with one claim and one verified audit event. This release does not recreate it.

## Capability and limits

SCORPIO9D1 **extends the preexisting owner-approved Work engineering mode** rather than adding an executor or granting a model new host permissions. When an owner submits an authenticated Work **engineering** run (`task_type=engineering`, `approved=true`) with an explicitly prefixed prompt, e.g. `SCORPIO9D1 TEXTUTILS: Build a four-function offline text-utilities library`, the existing `mio.work_engineering.execute_engineering` flow now:

1. Sends an explicit, pinned signature contract to the locally configured coding model. All model output is parsed strictly as data (flat Python/text filenames, size/AST checks). No shell commands are accepted.
2. Restricts this profile to exactly `textutils.py` and optional `README.md`. The model cannot supply, edit, replace, or choose the acceptance tests.
3. Executes the **trusted, immutable 13-test platform-owned suite** only via the already deployed Bubblewrap `sandbox_verify.sandbox_argv`, following the actual network/mount preflight. User, PID, network and IPC namespaces are isolated, and the entire sandbox filesystem is read-only. Resource/time/output limits apply. No model-provided command, package installation, Git command, network upload or host-shell fallback exists.
4. If independent tests fail, offers one bounded repair attempt to the local coding model using test output explicitly as untrusted feedback. The replacement candidate is parsed and reverified from scratch. No unlimited self-correction loop exists.
5. Preserves an immutable, owner-private, hash-verified artifact and a verifier manifest in the existing Work artifact store; a failed or unverified result is `needs_review`, never `answered`. The existing ZIP download flow remains usable.

Existing calculator behavior and ordinary Work research tasks are unchanged. Unprefixed requests are **not** silently upgraded to the new profile. No API changes, no dashboard changes, no access to production Git checkout, datasets, external API/MCP/skill execution, privileged filesystem writes, or self-modifying deployments.

## Operator workflow

Use an existing, explicitly selected Work project from the local Work UI. The owner must authorize an *engineering* run with an explicit phrase beginning `SCORPIO9D1 TEXTUTILS: ` followed by a meaningful task. Example:

`SCORPIO9D1 TEXTUTILS: Build a small reusable offline Python library for normalized whitespace, word counting, palindrome detection and ASCII slugification.`

The existing native Work API already requires the authenticated user's explicit `approved: true` for `task_type: engineering`. The existing independent Work worker (and only that worker) processes the run. If the model is unreachable or produces invalid code, the task fails or requires review rather than falsely claiming a completed artifact. No new user task/project is created automatically during release installation.

Review saved Work audit events and download the generated artifact ZIP via existing Work UI. The `verification.json` manifest includes test count and status. A passed platform suite demonstrates this narrow interface, **not** general code correctness, safety of arbitrary downloaded packages, or broad autonomous engineering.

## Release/rollback

The guarded release verifies Git `main` baseline, exact existing repo file blob, all 11 protected unrelated dirty worktree paths, preinstall Ruff for every new file and the proposed patched module, 13-test isolated Bubblewrap suite, focused/full pytest, dashboard TypeScript and SCORPIO9C5 real-worker acceptance. Only `mio/work_engineering.py`, `mio/scorpio9d1_textutils.py`, `tests/test_scorpio9d1_textutils.py`, `docs/SCORPIO9D1_BOUNDED_ENGINEERING.md` may be staged/committed/pushed. Non-force publication only. The controller checks the native Work queue is idle, takes a verified native-private SQLite backup, and restarts only the identity-checked Work worker, leaving API, dashboard, ComfyUI and the SCORPIO9C6 canary evidence untouched. On post-push failure, never duplicate/undo publication through Git; follow deployment-only recovery. Model and services must not be treated as validated beyond the specifically tested acceptance cases.
