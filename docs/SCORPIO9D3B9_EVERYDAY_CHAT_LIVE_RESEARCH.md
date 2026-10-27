# SCORPIO9D3B9 — Bounded live evidence in everyday Chat

## Problem / fix

Previously `assistant/ask` queued `ai_chat` and the worker always called
`supervise()`, whose system message correctly said the *offline* supervisor
had no web tools. As a result, even freshness questions such as “as of today,
is a researcher affiliated with an institution?” received generic refusals.

This phase routes time-sensitive prompts through an independently bounded
research helper before invoking the offline-only supervisor. It reuses
`studio_tools.web_search` (fixed public search providers, quality filtering)
and `web_evidence.enrich_sources` (public HTTPS, DNS pinned, no redirects,
limited bytes and up to three page excerpts). The local model receives inert
retrieved text as untrusted data. The final Chat message contains dated,
backend-produced public source links and explicit per-source evidence scope.

## Limitations and safety

- Ordinary Chat does **not** obtain the SCORPIO9D3B7 owner browser grant,
  general browser automation, headless Chromium, shell or filesystem access.
- No arbitrary model-chosen URL is fetched; search transport and public
  destination validation are already allowlisted and bounded.
- Snippets are not treated as verified pages. Missing public pages or invalid
  model citations produce an inconclusive answer, never a fabricated fact.
- Public affiliations do not establish live HR records. Report uncertainty.
- Ordinary nonfresh Chat stays on the previous offline supervisor unchanged.
- Neither this source release nor its tests creates a production chat task,
  restarts services, changes private production SQL or downloads packages.
- A separately approved API-only restart is needed to activate `mio.workers`
  in the running API worker. The dashboard and Work worker need no restart.

## Acceptance

Local helper tests cover routing, refusal of unsafe source URLs, snippet-only
handling, fabricated citation rejection, correct citation handling and untrusted
page instructions. The workstation controller then runs Ruff, focused and full
pytest, TypeScript, existing isolated worker acceptance, source snapshots and
service identities before a targeted git commit and push.
