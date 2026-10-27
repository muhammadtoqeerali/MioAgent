# SCORPIO9D3B10 — Shared read-only public web tool foundation

## Intent

Implement a common **search, open, cite** service, independent of any individual
named person or website. This is a first foundational phase toward consistent
online tools in Chat, Studio, Work and supported agent workflows. Source publication
alone does not activate the routes and does not provide full ChatGPT web-tool parity.

## New authenticated native-API endpoints

- `GET /api/research/tools`: read-only tool catalogue and explicit permission boundaries.
- `POST /api/research/search`: `{"query":"..."}`. Searches through the existing
  quality-filtered public provider, then attempts up to six existing public HTTPS
  results to collect at most three verified page excerpts. Returns source URL,
  snippet, verified/page-excerpt scope, UTC time and budget metadata.
- `POST /api/research/open`: `{"url":"https://..."}`. Reads one public HTTPS page
  with existing DNS pinning, TLS verification, size/time limits, no redirect,
  no cookies, no ambient proxy and no JavaScript. It cannot log in.

All routes use the *same existing native bearer-token requirement* as Studio.
The route registration occurs inside `register_studio_routes` in `mio/studio_api.py`
because that registration is already called by `mio/api.py`; the native API must
be restarted separately to load the new paths.

`mio.scorpio9d3b10_public_tools.check_citations` can reject references without
retrieved page excerpts, missing references and unbound IDs. A valid citation ID
**does not establish the factual truth** of the model's statement.

## Non-goals and security

- No model-generated tool invocations, autonomous agent execution, new credentials,
  browser navigation, network permissions to private IPs, or Work-grant issuance.
- The new service is a shared backend *available for integration*, not a claim
  that all four product surfaces automatically use it in this release.
- No source release should restart services, run production research tasks,
  modify production SQL, install packages or push from outside the approved
  guarded workstation publisher.

## Follow-on phases

Integrate Studio model responses with verified excerpts and citation checks,
then unify Chat and Work onto the same gateway and audit schema while preserving
their model routes, task lifecycle, and owner browser-grant boundaries. Continue
with PDF/DOI/scholarly providers, browsing of JavaScript-dependent public pages,
structured live-data tools and a broad evaluation set (not just KIOS).
