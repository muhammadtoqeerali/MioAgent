# MioAgent — local-first AI workstation assistant

**Master plan:** v1.0, adopted 2026-10-15. **Source:** `docs/MASTER_PLAN.md` (normative).
**Current implementation:** v0.1.0 foundation; **not yet a general-purpose AI agent**.

MioAgent aims to be a voice- and text-controlled, multi-agent engineering assistant with secure computer/browser control, code implementation, research, persistent memory, continuous improvement, and a high-quality operational dashboard.

## What actually works in Phase 1

- FastAPI REST API with locally generated bearer secret.
- PostgreSQL persistence of task records, results, progress, and timestamps.
- Durable single background worker with restart recovery for idempotent demonstration tasks.
- Allowlisted workflows: `demo_workflow`, `workspace_inventory`, and `echo`.
- Next.js command-center dashboard with genuine polling of API data, queue status, and task cancellation.
- Docker Compose stack bound only to loopback addresses.
- Unit/integration tests, CI, architecture and security documentation.

**Not implemented:** speech, wake words, AI reasoning, model routing, coding execution, browser automation, unrestricted computer access, self-learning. The dashboard labels these honestly.

## Requirements

Docker Engine, Docker Compose plugin, local port 3000 and 8000 available. The supplied workstation has Ubuntu 22.04, Ryzen 7950X, 187 GiB RAM, two RTX 4090 GPUs, Python 3.13, Node.js 22, and Docker 28. GPU infrastructure will be configured in later phases; the foundation requires no GPU runtime.

## Installation on the workstation

From the directory containing `compose.yaml`:

```bash
python3 scripts/init_env.py
docker compose --env-file "$HOME/.config/mioagent/.env" config --quiet
docker compose --env-file "$HOME/.config/mioagent/.env" up -d --build
docker compose --env-file "$HOME/.config/mioagent/.env" ps
curl -fsS http://127.0.0.1:8000/health
```

Open **http://127.0.0.1:3000** on the workstation. Services listen only on `127.0.0.1` on the host. For a remote workstation, prefer an authenticated SSH tunnel rather than exposing these ports publicly.

To stop containers without deleting database records:

```bash
docker compose --env-file "$HOME/.config/mioagent/.env" down
```

Avoid `docker compose --env-file "$HOME/.config/mioagent/.env" down -v` unless you deliberately want to delete the PostgreSQL volume.

To check logs:

```bash
docker compose --env-file "$HOME/.config/mioagent/.env" logs --tail=100 api dashboard database
```

## Deployment smoke test

After Compose reports healthy services, run `python3 scripts/smoke_test.py`. It verifies live API authentication, task creation, worker execution, and persisted results without revealing private credentials.

## API testing

```bash
set -a
source "$HOME/.config/mioagent/.env"
set +a
curl -fsS -H "Authorization: Bearer ${MIO_API_TOKEN}" http://127.0.0.1:8000/api/status
curl -fsS -H "Authorization: Bearer ${MIO_API_TOKEN}" -H 'Content-Type: application/json' \
  -d '{"kind":"demo_workflow","prompt":"check the persistent worker"}' \
  http://127.0.0.1:8000/api/tasks
```

The private `~/.config/mioagent/.env` file contains credentials. **Never publish it or paste its contents into chats.** On the supplied workstation, `$HOME` and the MioAgent source both appear to live under a mounted NTFS/FUSE volume. Thus storing `.env` outside the repository alone is **not proof of Unix file-permission protection**. Inspect `findmnt -T "$HOME/.config/mioagent/.env"` and migrate secrets to an owner-protected native Linux filesystem before allowing untrusted local users, remote access, or sensitive tools. See `docs/PHASE_1_REPAIR.md` for more detail.

## Developer tests

Use Python 3.12 or later:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
pytest -q
ruff check mio tests scripts
```

Dashboard type check/build:

```bash
cd apps/dashboard
npm install
npm run typecheck
npm run build
```

On the first workstation install, `npm install` produces `apps/dashboard/package-lock.json`. Commit that lockfile as part of the tested initial milestone to make future `npm ci` and Docker builds reproducible.

## Repository workflow

Create a local Git repository, push tested milestones to `https://github.com/muhammadtoqeerali/MioAgent.git`, and never commit `.env`, private data, model weights, or large datasets. Use short-lived feature branches and pull requests after the initial baseline.

## Important security scope

This is a **local development foundation, not an internet-facing production service**. The dashboard has no login and relies on host loopback binding and internal API bearer authentication. Do not expose ports 3000 or 8000 over public interfaces, reverse proxies, or untrusted tunnels until authentication, CSRF/origin policy, rate limits, transport security, and role-based permissions are fully reviewed. Terminal/code execution, browser control, external network automations, and model-proposed file writes are disabled in v0.1.0.

## Canonical project docs

- `docs/MASTER_PLAN.md` — authoritative roadmap and scope.
- `docs/ARCHITECTURE.md` — planned architecture and implementation status.
- `docs/HARDWARE_BASELINE.md` — verified hardware inventory and constraints.
- `docs/SECURITY_MODEL.md` — access boundaries and threats.
- `docs/PHASE_1_CHECKLIST.md` — gates to complete phase one.
- `docs/decisions/0001-adopt-master-plan.md` — architecture decision log.

## Phase 2 — Local AI supervisor (increment 0.2.0)

This increment adds a dedicated `/assistant` dashboard for real model-based text tasks, persisted conversations, descriptive two-step supervisor processing, and manually approved long-term notes. Models are reached through an OpenAI-compatible API (local Ollama first). No cloud access is enabled by default, and no shell/browser/computer tools run from model output.

See [Phase 2 installation and validation](docs/PHASE_2_IMPLEMENTATION.md). This release must pass the real workstation model smoke test before Phase 2 is considered complete. The existing Phase 1 demonstration tasks remain supported.
