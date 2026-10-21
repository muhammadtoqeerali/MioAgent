# B2B1 — Real engineering artifacts, an explicitly approved Work capability

Scope: Python source drafts stored in the private Work data directory. The worker
uses the configured local coding model. File paths are strictly flat and capped,
no shell is granted to models, no arbitrary host path is exposed or writable.

In Work, select **Python engineering** instead of **Research/writing**; accept
permissions; describe the calculator and specify mathematical acceptance criteria.
The separately running Work worker will generate real source, validate the
structured output, store content under `work/engineering/<run_id>`, and expose
`/api/work/runs/<id>/download` as a token-protected ZIP.

For a scientific calculator, a built-in independent trusted unittest suite checks
addition, subtraction, multiplication, division, zero division, power, sqrt, sin,
cos, and natural log. Generated code is executed only if a network-isolated,
read-only, unprivileged Bubblewrap sandbox passes its own preflight. A failing
model response may receive one bounded repair attempt; other Python projects
remain `needs_review` until independent user criteria and general-purpose tests
are added in B2B2. If Bubblewrap is not available or isolation is unverified,
source remains downloadable but is not declared tested.

## End-to-end acceptance (operator)

1. Verify all existing tests, typecheck, production build, API/worker/ComfyUI health.
2. Open Work and choose Python engineering. Submit **Build a scientific calculator**.
3. See `model.coding`, `sandbox.verify`, `sandbox.result`, `artifact.saved` events.
4. Confirm real ZIP contains `calculator.py` and `verification.json`.
5. If trusted tests pass, status may be `answered`; otherwise it must be
   `needs_review` with an explicit evidence limitation (never a fake pass).
6. Restart the API while an idle Work worker stays alive; verify the run persists.

Not yet included: unrestricted terminal, browser interaction, full-stack app
builds, automatic sandbox recovery after worker crash, GPU model tuning,
long-running developer tool autonomy. Do not claim B2B is finished from this
first slice; it must pass a real Work job on the operator's workstation.
