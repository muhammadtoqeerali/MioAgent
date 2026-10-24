# SCORPIO9B — local-model Supervisor draft proposals

This source release adds authenticated `POST /api/supervisor/propose` with
`{"project_id":"<existing Work project ID>","goal":"..."}`. Only a configured
local model on loopback may propose 1–6 bounded textual steps. No cloud fallback,
provider selection from user text, arbitrary web/tool invocation, shell execution,
filesystem modification, permission grants, or Work task dispatch is permitted.

The model output must be a strict JSON object containing exactly `steps`. It is
size-bounded and validated as untrusted data. Rejected, malformed, oversize,
cloud-routed or unavailable suggestions create no draft and no tasks. An accepted
proposal is saved as a **draft** in the existing native Work database; it remains
ineligible for worker dispatch until the owner separately approves it through
SCORPIO9A's existing saved-plan review. The event journal records `model.proposed`.

The existing Supervisor page receives a "Suggest draft with local model" action,
which is distinct from "Approve and run". Existing manual planning remains
available. This is **model-assisted planning**, not autonomous system administration
or autonomous self-development.

Next milestones must add isolated owner-approved capability grants and tool policy
checks before allowing sandboxed code generation/tests, then private checkpointed
self-improvement proposals. Do not let the same shared API bearer token become an
unrestricted owner-grant credential exposed to agents or untrusted model text.
