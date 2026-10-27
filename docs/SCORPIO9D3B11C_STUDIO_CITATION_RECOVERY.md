# SCORPIO9D3B11C — Bounded citation recovery for Studio research

## Evidence-based motivation

B11B was activated on the Ubuntu owner workstation at commit `27590ca29585aa8fc361d07681baec67e82c1f08`. The two-topic live Studio comparison confirmed science/ESA Hera research now returns three opened public excerpts with bound `[W#]` references, while software/Python research retrieves three opened pages but the local model sometimes omits or invents citation markers. The existing Studio gate correctly refuses that initial uncited draft. This phase is a **general model-answer recovery** feature, not a Python-specific exception or site-specific patch.

## B11C changes

- Only after source retrieval yields readable, verified public-page excerpts, and only when the first research answer fails existing shared citation binding, permit **at most one additional local model response** using the *same* opened page excerpts. The original untrusted draft is not supplied to the retry; source text is inert data, not instructions. A valid first draft triggers no retry or added inference cost.
- Retry permits citation IDs only from genuinely retrieved pages, never unverified search snippets. Bound revised citations are rechecked with existing `check_citations` and `checked_studio_answer`. Missing/unknown/malformed citations, model errors, or no verified pages preserve the current safe refusal. No fabricated certainty, synthetic citations or arbitrary URL loading.
- Studio's existing JSON contract remains unchanged; with a successful revision, `model` reflects the actual local model for that revision. File attachments, image mode, Chat and Work remain unchanged. All research stays in the established fixed search / pinned-TLS page-fetch path.

## Important limitation

This release validates **citation binding only**, not claim-level factual entailment. A valid `[W2]` marker does not prove that the sentence is supported by W2. Real semantic fact-checking, contradicted factual assertions and independent corroboration are future phases; never advertise B11C as a full factual-verification system.

## Publication and activation

A pinned, source-only workstation controller verifies the exact GitHub parent and two patch anchors in `mio/studio_api.py`, protected worktree, idle Chat/Work/Studio queues, service identities, preinstall Ruff, focused/full pytest, TypeScript and real-worker sandbox acceptance before allowlisted Git publication. No production process restarts until separate guarded API-only activation. Only the API needs a restart: the independent Work worker does not import B11C in its execution path.
