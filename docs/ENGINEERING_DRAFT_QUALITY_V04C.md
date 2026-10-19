# MioAgent v0.4C — bounded coding-draft correction and explicitly scoped retry

## Reason for this release

A v0.4B recovery of an existing user-owned multiplication goal reached the code-generation stage but failed with `Draft must contain 1 to 6 files`. Ollama was separately confirmed reachable and able to answer a small generation request. There is no evidence of a permanent Ollama or GPU outage. The cause of the empty/missing draft files is not yet proven (the original model output was not retained); the immediate defect is that a recoverable *format* failure permanently terminates project generation after a single response.

## Changes to agent behavior

* The Project Mode drafting worker sends a clearer JSON contract. It requires concrete, complete application Python source; authoritative acceptance tests remain owner-authored and inserted by the authenticated review-stage endpoint.
* The worker validates each draft with the existing strict `mio.project_mode.validate_draft`. If the model produces empty/malformed files, unsafe paths, syntax errors or no application Python source, it asks the same configured local model **once** for a corrected complete draft, with short normalized feedback. No model output is executed during generation and no unsafe draft is applied. There are at most 2 generation calls per project.
* The code-generation maximum output budget increases from 2,048 to 3,072 tokens, with a 270-second read timeout for that tier. Normal short chat/planning limits do not increase. The engineering supervisor's draft wait window becomes 660 seconds to account for one correction call. One GPU and local inference only; no paid APIs, packages or model downloads.
* Successful draft metadata includes `generation_attempts` for honest auditing. If both drafts fail, the project is marked failed and the error clearly says the two-attempt limit was reached.
* The original v0.4B once-only `--resume` was consumed. `--execute --restart-failed` provides **one** new private project run using the original saved validated plan and exactly the same goal digest. The previous failed project and report remain intact. It verifies the original project is still a failed, unwritten draft and has matching requirements; creates a separate private `*.retry1.json` report; and refuses replay if it already exists. A new project ID is expected; this is not secretly modifying an older project.

## Limitations

- This release provides **one bounded correction opportunity**, not guaranteed success. Passing provided tests does not prove correctness or security. The large generation request may still fail or return unsafe/incomplete code; such failures stop without applying an untrusted draft.
- No general shell or browser tool access, repository ownership, continuous learning, second reviewer, or autonomous task scheduling is enabled. This is still small stdlib unittest Project Mode with controlled approval.
- The first failed report was persisted on `/var/tmp`, which is not a durable long-term storage solution. This release does not perform backup, restore or server-side model migration.
- A previously submitted goal must not be retried by deleting the original report. `--restart-failed` is a separate, explicit one-shot workflow. Do not run concurrently against the same goal.

## After full release passes

```bash
cd /mnt/hdd16T/ToqeerHomeBackup/toqeer/MioAgent
PY="$HOME/.cache/mioagent/phase1-venv/bin/python"
"$PY" -m scripts.engineer_project docs/examples/v04a_multiply_goal.json --execute --restart-failed
```

This command creates a new project only after re-checking the original failed draft. Observe the output and private report. Desired result: all three owner's `unittest` methods execute and pass with original file SHA256 unchanged. If it fails, preserve both reports and the new project failure for further diagnosis, rather than repeatedly burning model inference cycles.
