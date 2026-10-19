# MioAgent v0.4B — local model gateway diagnostics and failed draft recovery

This intelligence-focused release is based on GitHub `main` commit `1238d37` (v0.4A). It adds no new paid APIs, remote servers, new models, skills, GPU allocations, or arbitrary shell/browser tool access.

## Why

The operator's first engineering goal successfully generated a structured three-step plan with `gpt-oss:20b`, but the follow-up code-generation project `6395c9f1-b8a1-4997-86e4-c15c8a80907a` failed with `local model unavailable (HTTPStatusError)`. A short standalone Ollama inference subsequently returned HTTP 200 in 8.6 seconds; this does not prove that full draft generation is healthy. The old gateway hid HTTP status codes and allowed only 120 seconds for every request. The controller recorded a stopped report but had no safe way to resume the failed project.

## Implemented

- Model-router errors now expose **HTTP status only** (e.g. `local model HTTP 500`), or timeout/transport/invalid-response class; no model error bodies, private prompts, API tokens, or upstream headers are disclosed.
- Local project drafting (`max_tokens=2048`) receives a 240-second read timeout. Shorter requests retain 120 seconds. No automatic retries, recursive LLM calls, cloud fallback or extra model downloads are introduced.
- Owner-authenticated `POST /api/projects/{project_id}/retry-draft` requires `{"approved":true}`. It accepts **only** a failed local-model draft with no staged draft/workspace or apply task, whose referenced draft task failed, and for which there is exactly one prior draft task. It atomically creates one new queued task on **the same project ID**, preserves the old failed task, and refuses any second retry, non-model failure or already approved project.
- CLI `python -m scripts.engineer_project docs/examples/v04a_multiply_goal.json --execute --resume` loads the **original private report**, validates the goal digest and structured plan, refuses any run that advanced beyond drafting, rechecks the failed remote project identity/title/requirements, explicitly authorizes its one retry, then continues test locking, approval, sandbox verifier and bounded source repair. The planner is **not called again**. The original test bytes remain immutable.
- New tests include authenticated API access, duplicate retry rejection, project state restriction, report privacy, goal/plan integrity, non-disclosure of upstream model errors, extended draft timeout and a simulated successful same-project resume.

## Operator workflow after successful publication

```bash
cd /mnt/hdd16T/ToqeerHomeBackup/toqeer/MioAgent
PY="$HOME/.cache/mioagent/phase1-venv/bin/python"
"$PY" -m scripts.engineer_project docs/examples/v04a_multiply_goal.json --execute --resume
```

Expected initial recovered project ID is `6395c9f1-b8a1-4997-86e4-c15c8a80907a`. Verify the CLI output and project ID match. It may take several minutes for Ollama to generate the full source. It may still fail if Ollama cannot complete the longer request. The new status code will guide further diagnosis. Never delete the private report to force retries.

**Safety:** `--execute --resume` explicitly delegates this one bounded run. It does not authorize Git publication of generated code, general shell commands, or internet access. If this retry fails again, stop and inspect the report; the current release deliberately permits only **one** retry per failed project. The running workstation database stays in `/var/tmp` and is not migrated by this release.

## Validation gates

Baseline exact `1238d37`, tracked index clean, no new file path collisions, both services up and task queue idle. Copy exact allowlisted files on NTFS, run focused and full pytest, Ruff, Next.js typecheck/build, pre-deploy Git whitespace/allowlist, private API smoke, controlled restart, new route existence check, exact staged Git files, then automatically commit and push. On failure before commit, restore original three source files and remove only new docs/test; restart original services if the API had been restarted. Preserve unrelated untracked files and all private data.
