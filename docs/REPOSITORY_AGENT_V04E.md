# MioAgent v0.4E: existing-repository engineering, not just new-file drafting

This is the next broad capability step after the verified v0.4D.3 two-model writing review.
It gives the local fleet an owner-controlled **read existing code → propose edits → run immutable tests → recover using another approved model → deliver diff → optionally apply** workflow. **It is not yet an unrestricted IDE agent.**

## What this release implements

- `scripts.repo_engineer`: goal preview (no LLM); optional `--execute` to run local model planning, generate full replacements for up to four owner-allowed existing `.py` source files, and run precisely selected pre-existing `test_*.py` files. Hard limits: 600 eligible tree files, 6 MB snapshot, 32 KB per edited source, three candidate attempts, 2–5 planning steps, bounded context and inference requests. Does not execute model-generated shell commands.
- Snapshot of actual repository sources; safe relative-path validation; skips `.git`, hidden files and generated/virtual environments; denies symlink-selected files, selected test edits, duplicate writes, escape paths, and new files.
- Runs the **baseline** and each proposed candidate using the existing no-network, read-only, no-GPU Bubblewrap isolation, only `/usr` and the controlled temporary snapshot mounted. Requires system Bubblewrap preflight, fails closed. The test harness imports **every explicitly selected test file** and verifies each has test cases. Test SHA-256s are checked before and after execution.
- Local `FleetRouter` provides per-role selection. If a model returns malformed edits, a different approved candidate may try; if edits fail acceptance, feedback is sent to the next candidate. Routing remains sequential and local. The source tree is **not changed by default**, even on passing tests.
- Durable private run record, per-attempt test outcomes and a unified `.patch` file in `/var/tmp/mioagent-native-1002/repo-engineering/<goal digest>/`. Existing audit reports cannot be silently overwritten or replayed.
- `--execute --apply` *explicitly* permits applying only passing, pre-authorized source files. SHA-256 checks ensure no concurrent changes to allowed source and tests. Private original source backups are written before changes. No automatic `git commit`, `git push`, network, model download, skills, university GPUs, or cloud inference.
- `scripts.repo_agent_demo` creates a fresh existing Python metrics repository with **two intentionally broken application modules and five existing tests** in a private runtime directory. It is not part of the source checkout. Running the demo fixture creation twice deliberately refuses overwrite.

## Requirements and limitations

- The existing v0.4D.3 fleet may remain active with `gpt-oss:20b` then `qwen3.8:27b` for planning/coding. If no private fleet is active, the original local gpt-oss router is used.
- The verifier uses root-owned system Python `/usr/bin/python3` and standard-library `unittest` in unprivileged Bubblewrap. Third-party package integration tests, Docker, custom shells, package installs, browser tasks, APIs and editable workspace dependencies are not supported by this release. No permissions are granted to the LLM to run external tools directly.
- The pre-existing source tree is snapshotted subject to size/extension limits. It is currently **Python-only** and requires explicit editable files and test files; it does not automatically choose the right edit scope. A passing test suite establishes only the specific tests passed, not semantic correctness or security.
- `/var/tmp` is not durable storage across OS cleanup/reboot. If `--apply` is used, preserve the original source backup or commit the changes on a dedicated branch. Apply is best-effort transactional, not fully atomic across files. Preview and sandbox trial modes are recommended first.
- Model output is untrusted. Repo text is treated as data; it grants no new tools. This experimental verifier is not a formal proof against malicious code and should not execute untrusted third-party tests outside its isolated environment.

## First real existing-repo demo

```bash
cd /mnt/hdd16T/ToqeerHomeBackup/toqeer/MioAgent
PY="$HOME/.cache/mioagent/phase1-venv/bin/python"
"$PY" -m scripts.repo_agent_demo
GOAL=/var/tmp/mioagent-native-1002/repo-engineering-demo-goal.json
"$PY" -m scripts.repo_engineer "$GOAL" # preview, no inference
"$PY" -m scripts.repo_engineer "$GOAL" --execute # model work, private diff, no edits to repo
```

To apply a previously passing sandbox candidate to the original repository, **first review the saved diff**, then run:

```bash
"$PY" -m scripts.repo_engineer "$GOAL" --apply-verified
```

This does **not** call any model again. It re-checks all original source/test bytes against the frozen baseline, re-executes approved tests in Bubblewrap and verifies the reviewed patch is unchanged. It saves original source backups in the private run directory. It refuses repeated approvals. Alternatively, a brand-new contract can run with `--execute --apply` to grant application from the start.

For other real repositories, create a JSON goal:

```json
{
  "repository": "/absolute/path/to/your/python-project",
  "task": "Explain and repair a precise bug in the existing application without changing the tests.",
  "editable_files": ["src/package/logic.py"],
  "acceptance_tests": ["tests/test_logic.py"],
  "max_attempts": 2
}
```

Start with preview, then run `--execute` and inspect `changes.patch`. The CLI does not publish changes automatically. For bigger projects and long-running agent sessions, the next phases need context retrieval, dependency-aware evaluation, source-control branches, resilient checkpointing, and dashboard tool-action review.
