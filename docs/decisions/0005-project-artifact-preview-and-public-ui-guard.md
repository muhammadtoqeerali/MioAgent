# ADR 0005: Guarded source artifacts as first operational Project Mode

- Date: 2026-10-16
- Decision: Accepted for implementation preview; not a production autonomy grant
- Context: The owner wants selectable chat or complete-project modes using local models, initial 1/2 workstation GPU budget, optional 2/4 university GPUs after authorization, minimal storage, and a stable Vercel web front-end. The adopted MASTER_PLAN.md v1.0 requires scoped permissions, controlled tool execution and workstation validation before a Git push.

## Decision

Add a durable Project record and queue-backed **draft → review → approve → create artifact** pipeline without running model-generated commands. Strictly limit generated file count/content/path/extensions; static-validate Python/JSON; store exact draft and hashes; write only after a new explicit user approval into an owner-private native Linux project root. Reuse the configured loopback model and turn off cloud within project tasks. Restrict university GPUs to zero until the campus workload guide and authorization are reviewed.

Add `/projects` Next.js page with status, source previews and approval. Leave existing Chat Mode untouched. Fail closed on Vercel proxy routes by returning 503 until a real identity/authorization/private-bridge system is completed. Retain v0.2.0 API version until a full end-to-end engineering release is ready.

## Consequences

Useful bounded source artifacts can be created and reviewed, but this does not count as complete autonomous project execution. `mio/resource_policy.py` remains advisory for future model placement, not an enforcement layer on Ollama/V100 schedulers. Native `/var/tmp` project storage is provisional and may be wiped. Long project autonomy, code sandboxing, backend access control for external users, repository tools, browser automation, resource accounting and persistent storage migration remain separate acceptance gates. No auto-push and no externally reachable control API.
