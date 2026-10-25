# SCORPIO9C1 Recovery3: bounded offline tool foundation

This initial increment does **not** add an agent executor, model tool calls, arbitrary shell, network, write access, self-modification, or external skill/API/MCP installation. Existing SCORPIO9A/B Work worker, running dashboard and API are intentionally unchanged. The registry is local-console-readable only; there is **no live `/api/tools/registry` endpoint** in this phase.

## Policy and execution

* Only an interactive local terminal under the owner UID can issue/revoke a grant; no HTTP route or model proposal may issue one. Terminal detection is not hardware-backed identity assurance; later implementations require a stronger explicit approval channel.
* The grant refers to an existing, separately owner-approved, still-active plan in the existing private Work SQLite. It binds UID, project, plan, exact tool ID, fixed owner-private input directory, filename, inode, device, size, content digest, and a 1–30 minute expiry.
* Owner input files live **only** under `/var/tmp/mioagent-native-$(id -u)/tool-inputs/PROJECT_ID/`, a real owner-private Linux directory (mode 0700); no arbitrary file paths, symlinks or NTFS permission assumptions. No installer creates projects or copies private files.
* Single-use grant is atomically consumed before a subprocess. The only permitted action is SHA-256 of one regular file <=1 MiB. Bubblewrap isolates network and host filesystem, exposes only system runtime libraries/executable and one read-only input FD, and scrubs environment variables. A failing isolation check is a hard denial, not a host-execution fallback. The tool returns a digest, not the raw file.
* Grant issuance, consumption, revocation and success are recorded in the owner-private Work SQLite. Revocation prevents future use, but cannot interrupt a short operation already consumed and in progress. Audits are not tamper-proof. Untrusted same-UID processes and host-kernel vulnerabilities remain outside this release's isolation guarantee.

## Manual use (only after the owner creates a real Work project and approves a plan)

Create the Linux owner-only input directory under your native runtime and place a reviewed small file there. **Never copy secrets or private datasets into it without a separate informed authorization.** You must use a real existing project ID and approved plan ID.

```bash
PY="$HOME/.cache/mioagent/phase1-venv/bin/python"
"$PY" -m mio.scorpio9c_console registry
"$PY" -m mio.scorpio9c_console input-folder --project PROJECT_ID
"$PY" -m mio.scorpio9c_console grant --project PROJECT_ID --plan PLAN_ID --file sample.txt
"$PY" -m mio.scorpio9c_console inspect --grant GRANT_ID --file sample.txt
"$PY" -m mio.scorpio9c_console revoke --grant GRANT_ID
```

This CLI is not yet available as a dashboard action. Only start real Work-worker tool integration after independent owner/session authorization, live backend policy gates, real sandbox denials and end-to-end run-state propagation pass. Disable external skills, MCP, OpenAPI adapters and self-development execution until each source/license/dependency and permission model receives explicit review.
