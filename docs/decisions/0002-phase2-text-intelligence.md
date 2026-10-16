# ADR-0002 — Phase 2 text-intelligence increment

**Status:** Accepted for staged implementation
**Date:** 2026-10-16
**Master plan:** 1.0 (unchanged)

## Context

Phase 1 is usable via a native no-sudo runtime and an SSH tunnel from the Windows laptop. Two RTX 4090 GPUs are available, but no local model server has yet been validated. The project directory is on a permissive NTFS drive; private development data and credentials remain in native-Linux restricted runtime storage.

## Decision

Implement model-agnostic OpenAI-compatible text inference as a small gateway rather than introducing LangGraph or multiple concurrent providers immediately. Add a two-call supervisor (descriptive plan, grounded answer); integrate queued requests with the existing persistent task store, add durable conversation tables and user-approved keyword-retrieved memory, and expose a dedicated dashboard workspace. Opt-in cloud model use is disabled by default. The model interface remains swappable with a future LangGraph graph or vLLM endpoint.

No autonomous filesystem, terminal, Git, or browser execution. All AI plans are display-only. Prevent model-provided URLs from reaching the HTTP gateway. Preserve existing Phase 1 database tables. Phase 2 model tests use injected mock responses, and live model readiness is verified separately on the workstation.

## Deferred

GPU model performance tuning, retrieval embeddings/vector DB, advanced workflow graphs, cloud budgets and comprehensive retries, concurrent model workers, voice interaction, tool execution, and durable process supervision. These remain in the seven-phase master plan; this ADR does not cancel them.
