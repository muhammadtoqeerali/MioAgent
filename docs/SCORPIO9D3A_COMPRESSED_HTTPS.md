# SCORPIO9D3A — Bounded compressed HTTPS evidence

Baseline `374d389f6f0dee7e4145e51d053ae88cfbc050f4`.

## Why

An owner-approved, read-only public HTTPS diagnostic failed with `Compressed page not supported` at `https://www.python.org/`. The previously accepted HTTP client intentionally sent `Accept-Encoding: identity`, but the remote server may still respond with compression. The diagnostic did not reveal the exact encoding; this milestone **does not assert** it was gzip.

## Scope

- Preserve `mio.web_evidence` DNS global-IP validation, pinned TLS address, public HTTPS-only target, no redirects, no cookies, no proxies, inert text-only HTML extraction, compressed byte limit and evidence provenance.
- Add a **stdlib-only** bounded decoder for `identity`, `gzip`, `deflate`; refuse Brotli (`br`), stacked encodings, invalid/truncated streams, trailing/multiple gzip members, and expansions over the original 420,000-byte bound.
- Keep the SHA-256 of the original received representation. Add a decoded-content SHA-256 and normalized content encoding for audit.
- Only existing bounded public research may call this client; this is **not browser automation, a binary downloader, package installer, arbitrary URL fetch permission or self-modification tool**.
- A live, owner-approved test of one known public documentation URL after code installation is necessary before claiming the original failure was resolved. An unsupported encoding is a legitimate, auditable failure, not a license to install decoders.

## Review and boundaries

No production Work run, project, permission, grant or canary is created by release. It runs syntax, Ruff, focused and full tests, frontend TS check, real isolated Bubblewrap acceptance, safe service/queue checks and exact staged Git publication before worker-only activation. Eleven unrelated dirty owner files remain protected. A private Work database backup precedes worker restart. No dashboard, API, ComfyUI, browser or package manager is restarted/installed.

Next phase (not enabled here): pilot a pinned Playwright build and cached Chromium in a private disposable environment with hostname restrictions and an owner approval gate for downloads/installations. Only then test bounded isolated browser behavior and a disposable two-attempt self-repair scenario. Production self-upgrades always require explicit independent approval.
