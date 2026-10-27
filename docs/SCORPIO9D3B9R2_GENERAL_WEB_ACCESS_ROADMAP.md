# SCORPIO9D3B9R2 — general web-evidence resilience, then unified tool access

## Mission

MioAgent/Scorpio is an owner-controlled, local-first research and engineering assistant. The KIOS-affiliation query was one evaluation example—not the goal or a special-cased feature. The product goal is broad, dependable online information access across Chat, Studio, Work and supported agent workflows; grounded citations and explicit provenance; and separately authorized actions where appropriate. Local model intelligence and tool access are independent: the local model can reason over retrieved evidence but does not inherently have web, data-provider, browser or application integrations.

## What the read-only production diagnostic established

- First three public search results: LinkedIn HTTP 999, personal profile over 420-KiB document budget, and ORCID lacking readable excerpt. All three were unverified. None of those outcomes imply that online research generally failed.
- GitHub (W4) was independently retrievable as a readable page with the person's name; it had not been attempted by the previous Chat pipeline. The IEEE page (W6) was readable but did not contain the subject in its excerpt. A static HTTP 200 page is not sufficient to establish answer relevance or claim truth.
- `mio.web_evidence.enrich_sources` was historically limited to attempts on the first three results, although search returned up to six. The same helper is available to other research paths.

## Scope of B9R2

Make **all six already-discovered public HTTPS results eligible** for bounded retrieval until **three successful readable page excerpts** have been collected. The existing six-result listing cap, 420-KiB/page limit, 7-second transport timeout, DNS pinning, public-IP requirement, TLS verification, no redirects, HTML extraction, no cookies, no ambient proxy, and no webpage JavaScript execution are unchanged. The fetcher never crawls new URLs. Retrieval failures are explicit snippet-only records. This helps general Chat and Work research without changing permission grants or creating jobs. Publication is source-only; production API activation remains a separate phase.

## Cross-mode target architecture (future phases; not claimed as implemented here)

1. **Shared read-only public research service:** a common `search`, `open`, `extract`, `rank`, and `cite` interface for Chat, Studio, Work and agent modes. Providers should include at least two independent public search transports, with optional approved APIs. Public research needs rate, time, byte and concurrency budgets, freshness checks, verified-versus-snippet labels, deduplication, topic relevance and citation validation. Normal public reading may be owner-configured as automatic; no login or modifying action is implied.
2. **Studio and Work parity:** reuse the same evidence records and source formatter in Studio answers, Work research runs and longer agent planning; distinguish file and web citations and keep source text inert. Ordinary Work research should not be required to have a manually pasted website URL once safe search discovery exists. Existing B7 single-use owner grants remain for its *browser automation* pathway until governance is deliberately revised.
3. **Broad content/document tools:** HTML/plaintext, PDF, scholarly metadata, DOI/Crossref/OpenAlex/PubMed, documents, feeds, structured tabular data, images, and video metadata or transcripts when providers allow them. Add provider adapters for live sports, finance, travel, location, currency and similar domain data. Each adapter reports actual availability, source time and access failure honestly.
4. **Interactive browsing:** browser engine for JavaScript-dependent pages, pagination and navigation with private-network denial, browser isolation, explicit domain/session authorization and per-run budgets. Logged-in websites, uploads, form submissions, purchases, downloads and changes to third-party data require scoped owner approval and auditable consent. Anti-bot protections, paywalls, robots rules and credentials may prevent access; no system can truthfully promise access to *every* website.
5. **Assessment:** general multi-domain evaluation matrix, not only a single affiliation question; fresh facts, difficult sites, conflicting sources, inaccessible sources, irrelevant results, malicious prompt injections, domain-specific feeds, latency and tool cost. Fail safely and report evidence quality, not fabricated conclusions.

## Acceptance and non-goals

- New isolated tests verify fallback past failed W1–W3, stopping after three successes, a hard maximum of six candidate attempts, and refusal to trust search metadata as full-page verification.
- Existing full pytest suite, Ruff, TypeScript, real-worker isolated acceptance and exact source/worktree/service identity checks are required before publication.
- No browser grant, host terminal, model-selected arbitrary tool, credential use, package install, Git operation outside the guarded source publisher or production job is introduced.
- This phase is **not** a claim that Chat, Studio, Work and all supported external applications already have feature parity with ChatGPT tools. That requires follow-on implementations and, for some providers, credentials or subscriptions.
