# Scorpio S12C — Offline Coding Workspace

This release adds a new authenticated owner-only API at `/api/scorpio/coding/*`,
private native-Linux SQLite job history, and a live Next.js page at
`/coding-workspace`.

**Scope:** Fixed platform-provided Python fixtures, two deterministic reference
repair attempts per job, the S12B3C tool broker and Bubblewrap-isolated selected
unittest execution. No LLM output, model requests, arbitrary repo access, owner
source application, privileged commands, KIOS access or cloud calls. The UI says
so unambiguously. This is infrastructure validation, **not** autonomous coding.

Owner creation requires `{ "case_name": "arithmetic", "approved": true }`.
A separate `POST /api/scorpio/coding/jobs/{id}/execute` with `{"approved":true}`
runs the synchronous, bounded rehearsal. Job state/events/results persist in
`/var/tmp/mioagent-native-UID/scorpio12c/jobs.db` (owner-only, 0600), separate
from existing Work data. Cancellation is immediate for drafts and cooperative
between attempts for active jobs. If the API crashes, `running` entries remain
visible for investigation; no falsely completed status or automatic resubmission.

The independent Git release is deliberately separate from enabling any future
model-driven or repository-write capability. Real agent inference remains blocked
until the owner-authorized inference service is restored and separately approved.

## Dashboard branding (S12C R2)

The locally approved gold-and-black Scorpio emblem is shown in the main dashboard sidebar from `apps/dashboard/public/scorpio-brand-gold.png`. The original `scorpio-mark.svg` is retained unchanged. The image is not a permission or agent-status indicator.

The integrated release builds the new dashboard into an isolated ignored `build/` directory while the prior dashboard remains running; only managed, idle services are restarted for the final verified build swap.

## S12C R3: regression-preserving gold branding

The global navigation uses a native HTML `picture` element. Its PNG `source` is the owner-provided gold emblem and the original `/scorpio-mark.svg` remains a real browser fallback. The screen-reader brand text remains Scorpio / AI AGENT PLATFORM. Existing dashboard contract tests are retained unchanged.
