# MioAgent v0.4A — Goal-driven engineering backbone

**First working connection of planning, coding, trusted acceptance tests, sandbox verification and bounded repair.** This is a preview for small local Python projects, not a Claude Code equivalent. It is separate from the encrypted-backup milestone. This release modifies one authenticated Project Mode endpoint, adds a goal-driven local supervisor CLI, and reuses the existing `v0.3D` repair runner; it does not create arbitrary shell/browser/Git execution privileges.

## Architecture and real workflow

```text
Owner-authored goal.json: requirements, concrete criteria, acceptance test source, 1–2 retries
 -> local gpt-oss:20b planner (validated JSON; retry once if invalid)
 -> capability registry role map: planning / coding / review; one model, zero external skills
 -> authenticated POST /api/projects (existing local model-generated source draft)
 -> authenticated POST /api/projects/{id}/acceptance (NEW, review state only)
 -> trusted server REPLACES any draft test files with the owner's exact acceptance tests
 -> server re-validates file inventory, safety constraints, source byte hashes, Python syntax
 -> delegated file approval only after test hashes match the goal
 -> existing Bubblewrap read-only stdlib unittest runner, no network/GPU/personal mounts
 -> existing local model repair proposals: one or two app source files per revision
 -> bounded runner automatically approves new source-only revisions under CLI --execute
 -> retests immutable original acceptance bytes, records pass/limit/failure and project IDs
```

This links a plan to the prompt used for code generation, rather than logging a plan without executing it. Planning/review are logical roles; **there is no independent second model or automated code reviewer yet**. Actual source implementation and repair use the existing local Project Mode model. The acceptance tests must be **written or explicitly supplied by the operator**, not trusted to the coding model. The API returns the original source unchanged and tests replaced before approval. The original project and repair revisions stay distinct.

## Safety and operational boundaries

- **No new paid APIs**, university GPUs, model downloads, skill installations, or additional GPU allocation. Existing `gpt-oss:20b` and the workstation's established Ollama connection are used; a single configured local GPU is expected.
- `--execute` is an explicit delegation for **the one JSON goal**: create small reviewed project files, run offline tests and approve at most two local repair revisions. It is **not** blanket terminal, Git, internet, browser or computer permission. The supervisor's API calls remain authenticated through the private native token; the public Vercel proxy stays intentionally disabled for privileged actions.
- Before approval, the new endpoint accepts only user-supplied `test_*.py` files, replaces model-written tests and revalidates the entire candidate through `mio.project_mode.validate_draft`. This can be used with other Project Mode clients only with existing owner authentication, project review state and sandbox flag.
- Acceptance tests are user-authoritative but still **not proof of specification completeness or security**. A criterion-to-task plan is a coverage map, not measured behavioral coverage. The planner is still a fallible local LLM. Current file limits are six files, total 64 KiB, and small Python standard-library unittest projects; the constrained sandbox is not a comprehensive security certification.
- Only `review` drafts can accept tests. Already approved original/revised projects cannot rewrite their tests. API never writes workspace files during the test-lock operation. The existing D runner checks SHA-256 after every revision.
- Reports contain goal digest, plan, project IDs, test hashes, run events and failure details in private `/var/tmp/mioagent-native-<uid>/engineering-runs`. **Still ephemeral**, not a permanent durable memory system. Verified off-machine encrypted backup already exists, but it is not a substitute for eventual durable runtime migration.
- A failed or interrupted run may leave an approved/queued project or a partial repair revision. Reports help manual recovery but this is not yet a transactional/resumable workflow. A goal digest cannot be executed twice without review. Do not run concurrent controller instances on the same goal or mix autonomous/manual operations on the same lineage.

## Input contract

Use the installed `docs/examples/v04a_multiply_goal.json` for a disposable trial, or create a small UTF-8 JSON file, e.g. `goal.json`, with exactly:

```json
{
  "title": "Verified multiplication utility",
  "requirements": "Implement math_ops.py with a correct multiply(a, b) function using only Python standard library.",
  "criteria": [
    "multiply(2, 3) must equal 6",
    "multiply(3, 4) must equal 12",
    "multiply(5, 5) must equal 25"
  ],
  "acceptance_tests": {
    "test_math_ops.py": "import unittest\nfrom math_ops import multiply\n\nclass TestMath(unittest.TestCase):\n    def test_two(self):\n        self.assertEqual(multiply(2, 3), 6)\n    def test_three(self):\n        self.assertEqual(multiply(3, 4), 12)\n    def test_four(self):\n        self.assertEqual(multiply(5, 5), 25)\n"
  },
  "max_repairs": 2
}
```

At least one meaningful `test_` method is required per criterion. The model does **not** author authoritative acceptance tests. File names must be flat `test_*.py`. The goal has a strict prompt/size budget; one or two test files only. Small application source `.py`, plus bounded accompanying text/config, are accepted. It may stop before approval for a malformed model draft, or when source/tests exceed policy. A test verification can legitimately fail and hit the repair limit. These outcomes must be reported as failures, not celebrated as success.

## Commands (Ubuntu workstation, after release)

```bash
cd /mnt/hdd16T/ToqeerHomeBackup/toqeer/MioAgent
PY="$HOME/.cache/mioagent/phase1-venv/bin/python"
"$PY" -m scripts.engineer_project docs/examples/v04a_multiply_goal.json
# Review the planned roles, criteria and local route. The above does NOT create a project.
"$PY" -m scripts.engineer_project docs/examples/v04a_multiply_goal.json --execute
# Explicitly delegates one bounded project; it WILL create/approve source and run sandbox tests.
```

The existing local dashboard `/projects` shows created and revised project files and verification logs. The engineering-run log is currently operator-only CLI JSON; richer timeline, diffs, approvals and model routing UI come later.

## Real acceptance gates

1. Structured local plan covers C1..Cn, bounded 3–7 tasks, no untrusted tool commands.
2. API rejects unauthorized test locking, refuses test updates after source approval, verifies model source unchanged, records user-authored tests as sha256-hashed draft data before applying.
3. Model draft is approved only after exact test hashes and source inventory validated; no model-produced fake tests survive.
4. Existing verifier executes owner-specified acceptance tests in network-isolated read-only Bubblewrap; number and outcome recorded.
5. Repair loop changes only existing non-test application Python, never acceptance code; stops after goal's budget. No Git push of generated work.
6. Full workstation pytest, Ruff, Next.js build, live API smoke, Git allowlist and controlled private-service restart before considering release successful.

## Next intelligence milestones (not falsely claimed complete)

- **v0.4B:** Independent reviewer/evaluator, richer requirement decomposition, test-case adequacy and coverage reports, context assembly with citations/line evidence, evaluation benchmark. Judge by task outcome, not plan prose.
- **v0.4C:** Hardened writable isolated developer workspace with exact tool permissions, scoped Git branches, safe package/network approval, working command executor; maintain a separate immutable acceptance verifier.
- **v0.4D:** Real model provider measurement and routing (Qwen3-8B vs gpt-oss:20b), optional LM Studio. Keep one GPU active by default. No university GPU use without IT permission.
- **v0.5:** Pinned/audited on-demand ECC and other appropriate SKILL.md instructions, not bulk 286-skill installation. Evaluated tool adapters only where they help. Agent memory/checkpointing and error recovery.
- **v0.6:** Original Claude-inspired responsive dashboard with agent timeline, file diffs, task events, approvals, context/model/skill usage and honest live status; continue to protect workstation APIs until robust remote auth is built.

**Honest limitation:** v0.4A can orchestrate an entire **small Python project** from an operator-specified goal if the local model and sandbox cooperate. It cannot yet autonomously own an arbitrary multi-language repo, install packages, browse, edit real Git repos, use paid frontier intelligence for free, or emulate Claude Code's full harness.
