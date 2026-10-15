# Architecture and implementation map

## Implemented in Phase 1

```text
Browser (localhost:3000)
  |
  v
Next.js dashboard -- server-side API proxy (API token kept server-side)
  |
  v
FastAPI (localhost:8000) -- bearer authorization -- allowlisted REST tasks
  |
  +--> PostgreSQL (private Docker network, durable volume)
  |
  +--> one worker loop --> demo task / echo / read-only inventory
                                 |
                                 +--> read-only mounted project workspace
```

`/api/status`, `/api/tasks`, `/api/tasks/{id}`, and `POST /api/tasks/{id}/cancel` are functional; credentials are generated in `~/.config/mioagent/.env`. `GET /health` intentionally needs no token. Job status is stored in PostgreSQL, running idempotent jobs are requeued on API restart, and the frontend polls every two seconds. The backend is a single-process demo executor, **not** a distributed job manager.

## Target after later phases

```text
Voice/text/dashboard -> intent router -> planner/supervisor
                                            |
                      +---------------------+----------------------+
                      |                     |                      |
                 coding agent         research agent         browser/OS agent
                      |                     |                      |
                 workspace              retrieval                approved tools
                      |                     |                      |
                      +----------- reviewer / policy ------------+
                                         |
                              audited durable task store
                                         |
                                dashboard + notifications
```

Agent processes must use explicit tool schemas and delegated capabilities. Model output must never directly become a shell command or unrestricted OS operation without policy enforcement. A central event stream, model/router abstraction, memory index, and permission approvals are **planned**, not present in the Phase 1 foundation.

## Data model (current)

A `tasks` table holds IDs, kind, prompt, state, progress, result JSON, errors, creation and update timestamps. Allowed status transitions are queued -> running -> completed/failed/canceled. Restart recovery requeues running idempotent jobs. This primitive executor should not be generalized to irreversible external tasks: those need durable tool-side idempotency keys and explicit approval state.

## Deployment notes

Host ports are bound to 127.0.0.1. PostgreSQL has no exposed host port. Dashboard routes proxy to the backend and hold the bearer token on the server. Private secrets are stored outside the project tree (`~/.config/mioagent/.env`); runtime artifacts are ignored by Git. Do not expose the dashboard to public interfaces until session authentication, CSRF/origin checks, authorization, limits, TLS and hardening have been completed.
