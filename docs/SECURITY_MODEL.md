# MioAgent security boundary

## Current foundation safeguards

- API/dashboard published only on `127.0.0.1` on the Docker host.
- PostgreSQL accessible only to services in the Compose network.
- API bearer token and database password randomly generated in a restricted home directory by `scripts/init_env.py` (never checked in).
- The browser does not receive the API bearer token: its same-origin Next.js server proxy injects the header.
- Task kinds are allowlisted; no arbitrary Python, shell, web or application control.
- Workspace folder is mounted read-only; inventory skips hidden and private file names and symlinks.
- Worker cancellation and restart recovery for deliberately idempotent operations.
- A README warning is included because localhost-only transport does not constitute complete production hardening.

## Must be done before remote/dashboard exposure

- Real dashboard login, secure session cookies, origin and CSRF protection, HTTPS, and a reverse proxy access strategy.
- Complete role and resource/action/duration permission model.
- Separate credentials per provider, audit logs, rate limits, clear API scopes.
- Sandbox quotas (CPU, memory, disk, network) for executed code; no privileged containers or Docker socket exposure.
- Defense against prompt injection, data exfiltration and malicious dependencies.
- Task event and action approval trail, emergency stop, and model/tool idempotency/retry policies.
- Browser profile isolation, data retention/deletion policies, backup/restore strategy.

## Controls that remain intentionally disabled in v0.1.0

- Microphone capture and transcription.
- AI model/tool execution.
- Arbitrary shell/host commands and full filesystem access.
- Browser automation and email or social-app actions.
- Autonomous internet research and self-modification.
- Public remote access.

## Implementation note

The dashboard proxy is intended for loopback-only use at present. It should not be considered safe for multi-user or internet deployment based solely on bearer-token injection. Add session authentication and CSRF protections before introducing tools with meaningful side effects.
