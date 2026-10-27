# SCORPIO9D3B5 — Public HTTPS evidence rendered in a network-disabled browser

Baseline: accepted SCORPIO9D3A Git commit `99a0b23401fae6975579a76326d615cf176e4544`.

## Scope

Owner approves **one** pinned demonstration URL, `https://www.python.org/`.
The existing `mio.web_evidence.fetch_public_page` is solely responsible for the
outbound public HTTPS request, including public-IP DNS pinning, no redirects,
no cookie or auth forwarding, and compressed-response size limits. Only its
short verified, extracted plain-text excerpt enters Playwright as HTML-escaped
text inside a `data:` URL. No raw web HTML, remote script, cookies or local
credential data is passed into the browser.

Chromium/Playwright uses the private owner-installed SCORPIO9D3B4 runtime, and
is constrained by Bubblewrap with `--unshare-all`, read-only browser/system
mounts, an empty home, and `accept_downloads=False`. A fixed local JavaScript
snippet must modify a DOM proof marker, and the rendered text SHA-256 must match
what was fetched. Browser process output is treated as evidence only if exact.

This phase **does not** implement a general website browser or unrestricted
navigation. It creates a test-backed reusable primitive and a user-approved,
standalone test command. It does not expose these APIs to model tool calls or
auto-grant network, package install, source edits, shell, or self-deployment.
Untrusted internet text is evidence and never executable instructions.

## Demonstration after release

From the pinned MioAgent checkout, with the tested private browser present:

```
$HOME/.cache/mioagent/phase1-venv/bin/python -B -m scripts.scorpio9d3b5_browser_demo \
  --approval 'APPROVE SCORPIO9D3B5 ONE PUBLIC DOCUMENT AND OFFLINE BROWSER TEST'
```

It prints JSON with the public HTTPS source hash, browser binary hash and
an exact-match offline JavaScript-rendering proof. It does not create any Work
run or modify the repository.

The next integration stage needs an **authenticated, task-scoped browser grant**
issued by the trusted service; the model must never mint grants or submit
arbitrary URLs. A separately vetted download/installer sandbox must then be
approved, followed by test-backed code proposal and explicit deployment review.
