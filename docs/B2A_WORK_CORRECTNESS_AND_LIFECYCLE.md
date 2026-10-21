# MioAgent B2A — lifecycle correctness before autonomous engineering

## Acceptance checkpoint

Previous B1/B1.2 and UX fixes remain running but uncommitted. The separately
managed Ubuntu Work worker and healthy ComfyUI are prerequisites. This phase
commits neither and performs no existing-state cleanup.

## Installed in B2A

1. **Archive** is reversible and backend-persistent. Archived entries disappear
   from ordinary Chat, Projects or Work listings. Restore brings them back.
2. **Delete** is permanent, only after an explicit browser confirmation. Backend
   chat messages, queued-job associations and terminal AI task records are
   deleted. Work project's runs, source/event evidence, instructions, memories
   and asset links are deleted. An unshared uploaded source file is unlinked;
   uploads shared by other Work projects remain intact.
3. Active Chat tasks and active Work runs cannot be deleted; active Work runs
   also block archival. This prevents deleting state that a worker is using.
4. Work page describes the **independent Ubuntu worker**, not the previous
   API-process execution. Unsupported computer tools remain disabled.

## Deletion semantics and privacy

- Deletion is an irreversible application-level DB/file removal, not an SSD
  cryptographic secure erase or purge of previously created system backups.
- Chat-generated Studio image PNGs currently lack a conversation-ID binding;
  deletion of a chat **does not** delete that separate Studio job/image.
- Unlinked Studio uploads not connected to the deleted project are outside its
  deletion scope. A shared upload is retained if another project links it.
- Legacy `/projects` artifact-project storage is not managed by the new
  `/projects-space` application and is not deleted by these controls.
- The Work deletion response lists any unexpected orphan file cleanup failures.

## Full Work phase acceptance still required

B2B must deliver **genuine** files to a strictly approved per-task workspace,
not a text-only research summary. Desired minimum job lifecycle:

- Supervisor parses goal, acceptance criteria and existing files.
- Supervisor proposes bounded plan and per-tool permission request.
- User explicitly approves workspace path (within a private root), read/write
  scope, resource limits and any external network access; default deny.
- Coding model writes only validated relative file paths in an isolated staging
  area; no `.env`, secrets, symlinks, `..` or arbitrary host writes.
- Human-approved acceptance tests run inside a verified Bubblewrap sandbox.
- Independent reviewer inspects code/tests and requests bounded fixes.
- Artifacts, test logs, approvals and the active worker lease are persisted.
- Interrupted jobs recover safely or show exactly why resumption is blocked.
- Work page and Control Room display the same durable state; only verified
  passed tests can mark an engineering assignment complete.

## Model optimization comes after B2B

Evaluate installed models per role with genuine realistic workloads and known
acceptance criteria. Compare correctness, token use, latency, GPU memory use,
reviewer reliability and image fidelity. Never infer superior quality from model
size or silently download unapproved weights.
