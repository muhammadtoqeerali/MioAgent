# SCORPIO9D3B11A — Studio joins the shared public research evidence pipeline

## Objective

MioAgent/Scorpio is an owner-controlled, local-first general research assistant. The KIOS example was a smoke test, **not a hard-coded product feature**. Chat and Work already have bounded public webpage evidence; Studio previously gave its local model only search-provider snippets and labelled those snippets as unverified. B11A upgrades Studio's existing research route to the B10 common search/open/citation core without changing Work approval boundaries.

## Change

- Studio's `/api/studio/respond` in automatic or explicit `research` mode calls `studio_research_sources`, which uses B10 `search_open` and the existing quality-filtered fixed search providers + pinned-IP public HTTPS reader. B10 tries up to six safe source URLs to collect up to three readable excerpts. Results are normalized with provenance and per-source `page_verified`/`scope`.
- If the question extracts a named person, search results must contain the full name, with at most one name-only retry. No subject is hard-coded.
- Only retrieved page excerpts are passed as factual web evidence to the local model, explicitly untrusted. Snippets are preserved in the returned source list with `page_verified=false` and never upgraded to evidence by a provider claim.
- Studio's research answers are checked against the shared `check_citations` binding validator. Missing/invalid/unsupported citations produce a transparent inconclusive response. A source-bound citation **does not prove** a claim's factual truth; the actual excerpt still needs human/source evaluation.
- The API retains the old response fields (`operation`, `answer`, `model`, `mode`, `sources`, `attachments`, `source_scope`). `source_scope` is upgraded to reflect actual opened pages. Existing text/image/attachment modes remain on their original pathways.

## Safety, limits and rollout

No arbitrary model-generated URLs, no JS browser, no network to private IPs, no cookies, no downloads, no login, no external mutation, no shell, no Work browser grants. Page reading remains DNS-IP-pinned, TLS checked, without redirects, and limited by B10/Work budgets. No change to provider credentials or cloud inference. B11A is source-only and requires separate owner-approved API activation. The independent Work worker and Next.js dashboard do not need B11A restarts.

## Follow-on phases

B11B will unify query planning, follow-up searches and evidence display across Chat and Work without discarding the existing name-focused and scoped worker safeguards. Later phases add controlled PDF/document reading, scholarly metadata, structured provider APIs and separately authorized interactive browser automation. No claim is made that every external website is accessible or that the local models have full ChatGPT tool parity today.

## Workstation acceptance

Checksum-pinned source ZIP, clean/pinned Git HEAD and blob hashes, protected-worktree snapshot, original service identities, idle Chat/Work queues, Ruff pre-install and installed, focused and full pytest, TypeScript, isolated worker sandbox acceptance, exact Git file allowlist and non-force push, private receipt; no production service restart during source publication.
