# MioAgent v0.3D — Operator-initiated bounded repair runner

This additive milestone **does not extend the web API privileges**, connect Vercel to a workstation, or enable arbitrary command execution. It provides a CLI that can take over the already-approved v0.3C sequence for **one existing project**, at most three iterations. No cloud APIs or additional GPUs.

## Execution conditions

Use on the workstation **only after the current v0.3C Project Mode and sandbox verifier are running**. The original project must be completed and have one or more `test_*.py` files. Its first verification may be run by this tool if none exists. The operator explicitly starts the bounded process with `--execute` and an exact project UUID. Subsequent repaired revisions are automatically approved **only within this exact project lineage**, using existing v0.3C server authorization and immutable-test controls.

The script re-hashes the acceptance-test file contents before every revision. If tests are added, removed, or altered, or changed source files exceed the existing one/two-Python-file repair policy, it stops. It will stop at any infrastructure timeout, task failure, unexpected status, repeated proposal, sandbox issue or invalid response. A new attempt cannot run after three repair iterations. It never invokes arbitrary shell commands from the model, commits project code, or pushes repairs to GitHub.

**Limitations:** Although test files are byte-identical, this does not prove requirements are satisfied. The original tests may lack coverage; generated code may still be insecure or incorrect. The v0.3C sandbox is read-only and supports only stdlib `unittest`. Checkpoints under `/var/tmp/mioagent-native-<uid>/repair-runs` survive worker restarts but not all OS cleanup/reboots. This is **not yet a durable production agent**. The run's per-project report blocks accidental replay, but it is not a transactional distributed lock; run only one process for a project and do not manually approve/re-verify the same project concurrently.

## Operator command

```bash
cd /mnt/hdd16T/ToqeerHomeBackup/toqeer/MioAgent
"$HOME/.cache/mioagent/phase1-venv/bin/python" -m scripts.autonomous_repair <PROJECT_UUID> --execute --max-repairs 2
```

The appends are recorded in private JSON alongside the local runtime database. The CLI's `--execute` is the user's delegation of **source revision approval for the bounded lineage**, not permission for arbitrary computer control or publication. Begin with a disposable failing Python project. Do not use on valuable projects until a secure durable data store and backup policy are in place.

## Release process

The additive release installs only `scripts/autonomous_repair.py`, its regression tests, and this document. The release process checks Git `HEAD`, prevents untracked source conflicts, runs full pytest and Ruff in the actual repository context, Next.js typecheck/build, and the live sandbox preflight. Only these three exact files are staged, automatically committed and pushed to the configured GitHub origin after passing. The current running API need not restart; this is a standalone CLI.
