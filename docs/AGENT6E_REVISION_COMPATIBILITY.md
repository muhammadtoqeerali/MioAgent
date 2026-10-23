AGENT6E revision-compatibility correction — 2026-10-23

The published owner CLI originally required Git HEAD to equal the earlier
AGENT6C commit, 69319d223fcfcee8983363e588e74292205cc2e4. The accepted
AGENT6E three-file release advanced main to f8712a8692a321e2521615119ed1e26a1b052720,
so the owner CLI's preflight would otherwise refuse every legitimate call.

The corrected CLI requires the checked-out HEAD to descend from the published
AGENT6E commit and requires all six original Work API/agent/planner modules to
remain byte-for-byte equal to the accepted AGENT6C versions. It still checks
selected source files against the checked-out Git HEAD, checks service identity,
requires both independent inspection flags, and demands explicit owner approval.

No live inspection submission occurs during installation or validation.
This patch does not expand inspection permissions, change API or worker code,
restart services, migrate live data, or grant shell or repository writes.

Previous approved owner CLI functionality remains at
scripts/mioagent_work_inspect.py. The new test module exercises descendant
acceptance and non-descendant/modified-source refusal, including throwaway Git.

If this correction is accepted on the workstation, publish only the three
approved files from this release in a later, separately approved scoped Git
commit. All vault/receipt data remain under .mioagent-private/ and ignored.
