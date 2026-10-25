# SCORPIO9C2 — Authenticated tool/grant visibility, no implicit approval

Base: accepted SCORPIO9C1 Git SHA `f2d52757bf955004252c1bc38739063f248c893d`.

## What is newly real

- `GET /api/tools/registry`: authenticated JSON describing the *single* currently vetted offline builtin digest tool, disabled external skills, disabled worker execution, and owner-console-only issuance.
- `GET /api/tools/grants`: authenticated, bounded, sanitized view of existing owner-UID grants in the owner-private native Work SQLite and recent grant event names/timestamps. It reports consumed, revoked, expired, inactive-plan, and still-available-console-only states. It never includes host paths, raw file contents, or input digests.
- The grant endpoint uses SQLite `mode=ro` with `query_only=ON`, checks directory/DB ownership and permissions, and does not create projects, grants, schemas or new Work databases.
- `POST`/`DELETE` grant routes **do not exist**. A general API bearer credential is NOT consent to issue, spend, revoke or escalate tool grants. Prior interactive local CLI remains the only owner issuance/revocation channel.

## Safety and operation

No changes to the independent Work worker, supervisor, dashboard frontend, image backend or Ollama. The API host is the *only* service requiring a controlled restart to load the new route. Existing Work data, all eleven unrelated files, and worker/ComfyUI PIDs are retained. A read-only HTTP 200 is not proof of autonomous task execution. Any dashboard-visible controls or tool worker execution must come in separately tested and explicitly approved releases.

The Next.js server-side same-origin proxy can access the two paths as `/api/proxy/tools/registry` and `/api/proxy/tools/grants`; its live service is unchanged. Remote/public Vercel management remains blocked. Avoid posting bearer tokens in messages or screenshots.

On an empty Work database the API must still return an authenticated `grants: []` response without silently creating Work projects. An unavailable or insecure private database fails closed with HTTP 503. Grant records remain console-only and single-use as implemented in 9C1.

## Future engineering (not granted by this release)

Integrate per-run and per-tool operation grants with the *existing* sequential worker after a trustworthy owner/session approval mechanism and revocation-at-tool-boundary are validated. Keep external SKILL.md instructions, MCP servers and remote APIs disabled until pinning, license/source review, credential isolation, network and data-transfer policies, tests, and explicit owner approval. Controlled self-development must produce reviewable sandbox proposals/tests; never auto-push, self-authorize or self-deploy.
