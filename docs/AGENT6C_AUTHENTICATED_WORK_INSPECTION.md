# AGENT6C — Authenticated, opt-in Work inspection

Baseline: MioAgent published `e66a2a0da00520abbee66034ca53a83c0443ba99`.

This phase integrates AGENT6B's bounded, static source-inspection plan into the
**existing native Work queue** without altering its SQLite schema. The API's
existing bearer authentication remains mandatory. The submitted task additionally
requires `approved: true` and an explicit list of 1–8 allowlisted source files.

The new feature is **OFF by default**. Both the API service and the Work worker
must be deliberately restarted with `MIO_AGENT6C_INSPECTION_ENABLED=1` before an
inspection can be submitted and executed. This installation phase does **not**
restart them or set their environment. No terminal, writes, persistent tool grant,
remote computer, network request, Git operation, model-driven function call,
or implicit authorization is added.

When activated in a later separately authorized phase, the existing authenticated
`POST /api/work/projects/{project_id}/runs` accepts:

```json
{
  "prompt": "Review Work agent source for maintainability",
  "task_type": "inspection",
  "approved": true,
  "sources": ["mio/work_agent.py", "mio/work_core.py"]
}
```

The Work queue stores the explicit source allowlist in the existing `sources`
JSON field while the job is queued. The worker validates it, reads those files
without following symlinks, performs static AST parsing without code execution,
and writes bounded SHA-256 evidence and stages into normal Work events/results.
It deliberately completes as `needs_review`, not `answered` or `verified`.

A boolean in an authenticated request establishes only the requester's asserted
approval; it is not an independent physical-presence confirmation. The system
therefore limits this phase to read-only allowlisted source inspection. The
VAULT5A persistent grant functionality remains disabled on the NTFS/FUSE mount.

The existing production Work DB stays on its native owner-private runtime under
`/var/tmp/mioagent-native-<uid>` until a separately validated storage migration.
The project-local snapshot remains additive and unencrypted on NTFS/FUSE.

## Acceptance

Install only when the source tree matches the pinned accepted `main` commit.
Validate patched source syntax, Ruff, native-memory pytest (including new
orchestration tests), and dashboard TypeScript. Keep `AGENT6C` disabled in both
live processes. Commit to GitHub only after workstation acceptance.
