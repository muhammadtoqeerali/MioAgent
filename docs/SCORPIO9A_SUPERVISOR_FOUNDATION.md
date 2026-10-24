# SCORPIO9A — owner-approved sequential supervisor foundation

This release adds real supervisor planning and automatic **bounded** Work queue
handoff, backed by the existing native `work.db`. It does not create a new
runtime database, launch an independent worker, install a general computer-use
agent, or grant host tools.

## Actual operation

1. Owner selects an existing non-archived Work project. No project is created
   implicitly or reassigned from one database to another.
2. Owner submits a goal and 1–6 specific bounded prompts. This is a saved **draft**:
   it does not dispatch tasks or call an LLM.
3. Owner reviews every step and explicitly approves. An audit entry is saved.
4. The existing independent Work worker transactionally queues the first step.
   The Work agent runs with its existing restrictions; no shell, arbitrary paths,
   workstation control or privilege delegation are granted.
5. After a Work run becomes `answered`, the worker records the outcome and may
   queue the next approved step. The global one-Work-run-at-a-time limit remains.
6. `needs_review`, `failed`, `interrupted`, unknown states, or archiving stop
   automatic continuation; no retries or checkpoint resumption are forged.
7. Owner can pause **future** dispatch, not abort a current running Work task.
   Resuming requires another explicit approval.

The new authenticated API routes are `GET/POST /api/supervisor/plans`,
`GET /api/supervisor/plans/{id}`, `POST /api/supervisor/plans/{id}/approve`,
and `POST /api/supervisor/plans/{id}/pause`. The persistent Scorpio sidebar
adds `/supervisor` and the page polls actual saved state and displays Work run
links. SQLite schema extensions live in the original native Work DB and use
foreign-key cascades for existing project deletion behavior.

## Security boundary and forward milestones

9A is **sequential approved-task orchestration**, not open-ended planning, auto
self-modification, or unrestricted autonomous computer control. Next releases
will add model-assisted plan proposals with independent owner review, persistent
permission grants with scope/expiry/revocation, sandboxed code/file tools,
verification checkpoints, and tested self-development in quarantined branches.
Never let agents silently approve their own plans, mutate the Git worktree,
restart services or expand permissions. Existing audit rows are durable SQLite
records, not tamper-proof proof of execution. Automatic downstream steps are
limited to the preapproved owner text and the existing bounded Work capabilities.

## Production data warning

The current API preflight on 2026-10-24 reported **0 Work projects and 0 runs**.
This is not assumed to match older historical project/run identifiers. Before
creating your first plan, confirm that the real `/api/work/overview` lists the
expected project; if not, stop and investigate storage identity rather than
migrating/deleting/creating a replacement data store silently.

## Validation and publication sequence

Guarded source installation → focused and full native-memory regression →
reviewed acceptance receipt → **selective commit + GitHub push together** →
separately owner-authorized Work worker and API + dashboard activation with
PID identity and database backup/rollback. No service action occurs at source
installation time.
