# MioAgent Phase 1 — Native, no-sudo development runtime

**Status:** alternative deployment path for workstations without Docker daemon permission.
**Scope:** Phase 1 demonstration tasks only. No model inference, computer control, or voice commands.

## Why this exists

The user has Docker CLI installed but no rights to `/var/run/docker.sock` and no `sudo` password. The Docker group is root-equivalent; do not change the socket's permissions to bypass policy. Rootless Docker is an optional future direction once its prerequisites are confirmed.

The Phase 1 backend supports SQLite, so native execution can verify the same API and worker behavior without Docker/PostgreSQL. PostgreSQL-backed Compose deployment remains an unverified acceptance gate, **not** a completed milestone.

## Setup / validation

From the project directory:

```bash
VENV="$HOME/.cache/mioagent/phase1-venv"
"$VENV/bin/python" -m pytest -q
"$VENV/bin/python" -m ruff check mio tests scripts
npm --prefix apps/dashboard install --no-audit --no-fund
npm --prefix apps/dashboard run typecheck
npm --prefix apps/dashboard run build
python3 scripts/native_runtime.py start
python3 scripts/native_runtime.py smoke
python3 scripts/native_runtime.py status
```

Open http://127.0.0.1:3000 on the workstation. The dashboard and API listen only on `127.0.0.1`.

To inspect logs: `python3 scripts/native_runtime.py logs`.
To stop: `python3 scripts/native_runtime.py stop`.
To restart: `python3 scripts/native_runtime.py stop && python3 scripts/native_runtime.py start`.

## Runtime data and secrets

`/var/tmp/mioagent-native-<uid>/` is checked to be on a native Linux filesystem and owned by the user with mode 0700. The API bearer token is generated under this directory with mode 0600, and its value is never printed by the runtime helper. SQLite data lives under `data/mioagent.db`. Unlike the existing `~/.config/mioagent/.env` on NTFS, these new native credentials are not placed on the permissive drive. The old NTFS credentials may still exist; treat them as exposed to other workstation users and rotate them before later privileged capabilities.

`/var/tmp` may be cleaned by system maintenance. This is **not permanent production storage**. The native runner doesn't restart after reboot and is not a substitute for container sandboxing. A durable owner-protected location and proper supervised services are needed in later phases. The source directory itself is on NTFS; another local user may be able to modify executable source files, so this deployment is suitable only on a trusted development workstation and not for sensitive tasks.

## What the smoke test proves

1. FastAPI returns `/health`.
2. API bearer-token authentication succeeds.
3. Next.js proxy connects to FastAPI.
4. A new `echo` task is queued and executed.
5. Result can be retrieved from SQLite persistence.

This **does not verify PostgreSQL**, Docker image builds, multi-agent AI, privilege isolation, or reboot recovery. Do not report those as complete.

## GitHub milestone policy

Commit this fallback runtime alongside the already corrected Phase 1 source and `apps/dashboard/package-lock.json` after native smoke passes. The Actions CI runs lint, tests and frontend build. It does not run Docker Compose by default.
