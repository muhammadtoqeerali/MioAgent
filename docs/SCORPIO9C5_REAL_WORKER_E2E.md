# SCORPIO9C5 — Real worker end-to-end isolated acceptance

Baseline: `09d2f05999bd3f87070614ab1b07e1a8662a9437` (accepted SCORPIO9C4).

## Scope and distinction from production tasks

This release adds **no new privileges, agent runtime paths, HTTP handlers, third-party integrations, service restarts, or model auto-approvals**. Its deliverable is a repeatable, independent, real-process acceptance of the existing native sequential Work worker and Bubblewrap digest tool. Tests intentionally operate on **synthetic test-only** projects, files and grants under freshly generated native Linux private directories. They never write to the actual `$RUNTIME/work/work.db` or create owner project records in that database.

The harness calls the deterministic `_stage` fixture helper to prepare synthetic grants. That is *test setup*, not a bypass made available to the model, API or production worker. In production, `mio.scorpio9c3_console stage` still requires an interactive local owner terminal, and the owner must separately approve the real supervisor plan.

## Real acceptance scenarios

- **Sequential success:** two different files and two exact approved steps; two single-use grants; the actual worker process runs both through Bubblewrap, records two verified digests, and completes the plan in order.
- **Revocation:** a revoked staged grant never reaches Bubblewrap; the run enters `needs_review`, and the plan enters `attention` without retry.
- **Expiry:** the same denial on an expired grant.
- **Changed input:** a modified input hash is rejected before grant consumption.
- **Unbound step:** a digest-looking prompt without an owner-staged grant is denied rather than passed to the model for a fabricated answer.

All cases verify saved SQLite run/step/plan events. They remain settled during further worker polling; workers are signaled only via the explicit Popen handles belonging to the test harness. Nothing probes or terminates unknown PIDs. The synthetic subprocess receives a minimal environment: no inherited tokens or cloud credentials, no configured model, cloud disabled. Bubblewrap remains mandatory and has no unsandboxed fallback.

## Operator workflow and one-command release

The guarded controller checks pinned `main`, origin, clean Git index, and preserves the byte hashes and dirty status of all eleven pre-existing owner files. It checks each candidate Python file with Ruff **before source installation**, then runs focused tests (real isolated worker), the full native pytest regression, TypeScript, and a complete fresh standalone acceptance. It verifies source bytes, exact Git staged/committed paths and GitHub non-force push. Existing API/dashboard/worker/ComfyUI PIDs must not change. After publication, it verifies live service health and writes an ignored nonsecret receipt.

Manual re-run of the acceptance only after installation:

```bash
PY="$HOME/.cache/mioagent/phase1-venv/bin/python"
"$PY" -B -m mio.scorpio9c5_acceptance --mode isolated \
  --approval 'APPROVE SCORPIO9C5 ISOLATED WORKER ACCEPTANCE NO PRODUCTION TASKS'
```

This validates an *actual isolated Work worker subprocess on the workstation*, **not** a real persistent owner project and not a click-through demonstration of production owner approval. The real-owner manual sequence remains documented under `docs/SCORPIO9C4_WORKER_EXECUTION.md` and should be exercised by the owner separately using a non-sensitive sample and consciously created Work project. No production Work project or grant may be auto-created simply to complete acceptance.

## Boundaries and next steps

Existing `GET /api/tools/registry` and `/api/tools/grants` remain read-only. Skills and APIs may be inventoried later but are not executable, network access is disabled for digest tools, and no arbitrary shell or self-modification exists. After acceptance, the next milestone can consider a **real owner-driven live workflow**, plus separately reviewed bounded write/test tools and a stronger owner/session authorization channel. No automated Git push, merge, deployment or self-granting is permitted for agents.

## Recovery1: unbound grant-table race and worker teardown

The original SCORPIO9C5 pre-publication test stopped while snapshotting an
**unbound** digest step: unlike staged cases, the `scorpio9c_grants` table
may not exist until the worker has first processed the run. The snapshot now
checks `sqlite_master` and treats an absent grant table as an empty inventory,
without creating schemas or granting anything. Worker cleanup also accepts
SIGTERM issued to a test child before it has installed its signal handler,
while preserving the original test failure if cleanup itself fails. Dedicated
regression tests cover both conditions. This is acceptance-harness-only; no
production Work worker or tool policy code is changed.
