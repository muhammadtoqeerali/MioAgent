# SCORPIO9D3B6 — One-use scoped public-document browser grant

Baseline: `26ce3fd3acd640c6e09f9d3ab073707be9f25e46` (accepted B5).

The existing B5 browser is **offline-only**, receiving inert escaped text retrieved separately by B3A's guarded public-HTTPS client. This milestone adds a strict **run-/project-/exact-URL-bound, max-five-minute, single-consumption capability** in a separate owner-private SQLite ledger under `/var/tmp/mioagent-native-<uid>/scorpio9d3b6-browser-grants/`.

Grant issuance is demonstrated through a separate owner-invoked CLI with an exact approval phrase. Model output is never interpreted as an approval; a future *authenticated Work API* will be the only owner-facing issuer. A boolean parameter on the core primitive is **not itself authentication**; it must only be invoked by an already authenticated owner route or the guarded demonstration CLI. This milestone intentionally does not connect the broker to the Work API or a model tool. The demo uses a fresh synthetic project/run binding, not a real Work run, and creates one spent private grant. The original Work database is not modified.

The claim transaction atomically marks the grant as used **before** the public request. Failures or process crashes do not silently replenish the capability. The ledger stores SHA-256(token), not the bearer token. Verified page and offline rendering digests are stored after successful execution; failures remain marked failed, and crashes remain claimed for owner review. The renderer has no browser network, no downloads, and no installer, host shell, repository source writes, deployment, or extra model permissions.

## Acceptance

- Preinstall Ruff for every new Python file; focused and full pytest; TypeScript; real-worker Bubblewrap isolated acceptance.
- One owner-approved live one-page fetch to `https://www.python.org/`, then offline Playwright rendering using the previously verified SHA-pinned browser.
- Exact baseline and worktree protection; Git changes limited to this module, demo, tests and document. No managed service restart. The controller fails closed on any extra changes and preserves the eleven protected dirty source files.

## Next milestones

1. Authenticated Work API and UI Approve/Reject issuance bound to a real Work run ID, plus real worker pickup and run events.
2. Separate download-quarantine capability with byte limits, content hash, malware/package provenance checks; no execution of downloaded files.
3. Disposable dependency-resolution and isolated build/test/repair pipelines. Tested repository patches remain private until separately approved to apply/publish.
