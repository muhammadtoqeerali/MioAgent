# ADR 0001 — Adopt MioAgent master plan 1.0

**Date:** 2026-10-15
**Status:** Accepted

## Decision

Use `docs/MASTER_PLAN.md` as the authoritative design and seven-phase development baseline. Build a local-first system with a Python/FastAPI backend, a Next.js dashboard, PostgreSQL-based task persistence, scoped external tool access, local/cloud model routing and governed continuous improvement.

## Consequences

Deliver features as substantial tested milestone batches, with GitHub synchronization after validation. Keep permissions and secrets outside model prompts, use documented approvals, and distinguish planned capabilities from implemented ones.

## Future revisions

Any significant plan change requires a new ADR recording options, reasoning, effects on the roadmap, and migration details.
