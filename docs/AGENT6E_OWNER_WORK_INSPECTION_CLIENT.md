# AGENT6E — Owner-facing live Work inspection

Published source baseline: `69319d223fcfcee8983363e588e74292205cc2e4`.
Requires accepted AGENT6D activation of **both** native API and Work worker.

This phase adds an operator-facing command; it does **not** alter existing API,
worker, engineering executor, database schema, services, or model permissions.
No automatic tasks are created by installing or testing the command.

- `--mode preflight` verifies the published source, manager-recognized live
  processes, dual feature gates, owner-private token availability and source
  allowlist. It performs no production Work task.
- `--mode submit` requires the literal owner approval, a 32-character ID of an
  existing Work project, and 1–8 explicitly chosen tracked source paths. It
  submits exactly one authenticated read-only Work inspection using the
  existing API; checks task state, audit events and pre/post source hashes;
  and creates a small sanitized audit receipt under
  `.mioagent-private/agents/audit/agent6e/`.

Example production invocation **only after installation acceptance**:

```bash
$HOME/.cache/mioagent/phase1-venv/bin/python scripts/mioagent_work_inspect.py \
  --mode submit \
  --project-id 8937c5e4a84e4447b3dcbbf171615115 \
  --source mio/work_agent.py --source mio/work_core.py \
  --approval 'AGENT6E AUTHORIZE ONE AUTHENTICATED READ ONLY WORK INSPECTION'
```

The CLI prints neither API secrets nor inspected source code. `needs_review`
means *evidence recorded and owner review required*, **not** automatic code
changes, tests, a verified fix or autonomous execution.

Deployment caution: the project is on NTFS/FUSE with world-writable checkout
semantics; the project-local audit is not OS-private and is not encrypted.
The live Work SQLite database remains in its native Linux owner-private runtime.
The existing persistent grant system is still disabled.

Do not turn on host shell access, write repo patches, or restart services to use
this release. Git publication remains separate and only after acceptance.
