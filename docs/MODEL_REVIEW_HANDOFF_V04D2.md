# MioAgent v0.4D.2 — Qwen independent review handoff

Observed v0.4D failure: the activated two-model writing trial produced the first answer using `gpt-oss:20b` but stopped during the Qwen second-model review: `local model invalid response (ValueError)`. This error means the OpenAI-compatible completion did not provide nonempty final `message.content`; it does not prove a GPU failure or poor model quality. We do not know whether the model exhausted its 850-token budget in its thinking trace or encountered another response-format problem.

## Change

- `FleetRouter.prefer_direct_answer`, **off by default**, enables the documented native Ollama `/api/chat` endpoint with `think: false` for a Qwen3-family reviewer only. No internet, credentials or paid providers; all model names and SHA256 digests are checked against the existing activated private allowlist.
- For Qwen review, the CLI uses a bounded `num_predict=1800`, rather than `850`, to give the reviewer a meaningful output budget. Other coding, chat, planning, and repair settings remain unchanged. The native API returns only `message.content` to users, never internal reasoning fields.
- HTTP codes, timeouts and invalid final content are reported as safe failure types without leaking response bodies, prompt text or keys. If final content remains empty or the model does not support `think: false`, the review stops instead of inventing a critique.
- The writing command is reminded not to assert trial results or measured improvements without evidence. This is a prompt-level mitigation, **not** a guarantee of factuality. Review should specifically reject fabricated preliminary results and unsupported claims.

Ollama documentation: https://docs.ollama.com/capabilities/thinking — native `think` option, final response in `message.content`.

## Not modified

The active `/var/tmp/mioagent-native-1002/model-fleet.json` is preserved. No new models, GPU allocation, skill installation, backup change, university compute or cloud provider. The default single-model behavior when policy is disabled remains unchanged. Existing reports and Git-untracked files remain untouched.

## Verification

After successful release publication, use the same prompt path from the earlier trial:

```bash
cd /mnt/hdd16T/ToqeerHomeBackup/toqeer/MioAgent
PY="$HOME/.cache/mioagent/phase1-venv/bin/python"
"$PY" -m scripts.model_fleet show
"$PY" -m scripts.model_fleet ask \
  --role writing \
  --prompt-file /var/tmp/mioagent-native-1002/fleet-trials/writing-trial.txt \
  --review --refine
"$PY" scripts/native_runtime.py status
```

Success requires three **different stage outputs**: a draft by gpt-oss, a critique by approved Qwen, and a revised answer by gpt-oss. The critique is advice, not truth or externally verified evidence. If Qwen returns a different error, share only the safe error type/status; never paste credentials/private internal files. Further complex multimodel execution and real repository tooling remain separate milestones.

## v0.4D.3 test-harness hardening

The v0.4D.2 workstation validation found three failures in legacy Chat,
Project Mode and repair tests, despite 93 focused passes. These older tests
mock `ModelRouter.complete` while the user's now-active private fleet policy
caused the actual workers to instantiate `FleetRouter` instead. The failures
reflect test dependence on operator machine state, not proof of a Qwen review
regression.

`tests/conftest.py` now gives every pytest case an isolated owner-private,
missing policy path. Fleet-specific tests still pass explicit simulated policies
and digests, so production routing continues to be tested. The test fixture
never disables or edits the user's active `model-fleet.json`. A dedicated
regression test ensures the live policy is not visible in ordinary tests.

The Qwen direct-answer review fix is unchanged. Live Qwen review, full tests,
API smoke and safe Git publication must still succeed on the actual workstation.
