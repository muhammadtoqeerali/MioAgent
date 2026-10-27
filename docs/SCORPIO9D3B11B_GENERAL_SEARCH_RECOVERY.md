# SCORPIO9D3B11B — Bounded search recovery and no-evidence response

## Evidence from production

B11A completed the Python stable-release research with three opened excerpts and bound references. Python 3.15.2 is confirmed on official Python.org as of October 27, 2026. A second Studio query about ESA Hera failed with HTTP 422 (no topic-relevant sources). Citation ID binding is not semantic entailment and no claim of full factual verification is made.

## Scope

- Shared search-quality layer removes generic 'According to public sources' and trailing citation instructions before searching. Existing provider, domain and relevance rules remain in place.
- On lack of candidates, both fixed providers are independently attempted for a reduced topic query. One additional *compact* (first five distinctive terms) retry is allowed for long topic questions; source results are still scored against original topic terms, never blindly accepted.
- Studio research treats provider absence as a normal inconclusive research result, not HTTP 422. It returns a clear zero-evidence answer or snippet-only statement **without invoking the model** when no verified excerpt is available.
- Other modes that use `mio.studio_tools.web_search` automatically benefit from the shared query recovery once their processes are separately restarted. No page-download budget or network permission is changed.

## Explicit non-goals and future work

This does not guarantee live search-provider reachability or semantic fact-checking. It does not grant arbitrary URLs, browser automation, logins, downloads, file writes, shell or external actions. B11C will add claim-to-excerpt verification and a structured multi-domain live evaluation harness. Next phases unify planning, repeat searches, document/PDF readers and provider-based structured tools across Chat, Studio, Work and agent workflows. No single-provider result is treated as verified merely because a search matched.

## Release discipline

Exact commit and Git blob preflight, protected modified owner files, idle Work and Chat queues, unchanged service identities, preinstall Ruff and complete installed Ruff/pytest/TypeScript/worker acceptance, exact file allowlist, non-force Git push and private receipt. Source publication does not restart the running API or worker; separate owner authorization is required for activation.
