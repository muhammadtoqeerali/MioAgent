# SCORPIO9D3B8 — owner browser decision UI (source-only)

Connect the already activated SCORPIO9D3B7 authenticated Work browser proposal and decision endpoints to `/work-mode`. This is UI-only; `mio/scorpio9d3b7_work_browser.py` retains the sole authority to issue and consume browser grants.

## Owner workflow

1. Open an existing Work assignment after its active task completes.
2. Enter a task goal and **one exact public HTTPS URL**.
3. Select **Request browser approval**; this stages an inert `needs_review` proposal. No grant is issued.
4. Review the exact URL and task, then select **Approve once** or **Reject**. Both decisions go through the authenticated Work API and are audited server-side.
5. The independent Work worker uses the already activated B7 one-use browser binding; the page refreshes server-backed Work results and events. The browser remains network-disabled and only receives escaped evidence text.

This iteration requires the owner to supply the URL. The model **cannot** currently discover a URL and request a grant through Work; that requires a separate audited URL suggestion feature. Everyday Chat (`assistant/ask`) does not use this UI or browser broker and will be addressed separately.

## Operational separation

The source-only controller builds and validates TypeScript and all Python regressions without changing service processes, installing packages, creating a production run, or launching internet browser tasks. A separate dashboard rebuild/restart must be approved to activate this UI. Do not restart the API, Work worker, or ComfyUI for UI-only activation.
