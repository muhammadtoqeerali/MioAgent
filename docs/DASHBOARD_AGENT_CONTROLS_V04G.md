# MioAgent v0.4G — Owner-registered repository engineering in the dashboard

This release builds on published v0.4F `7ff28a5`, retaining the local fleet and the proven v0.4E Bubblewrap verifier. The interactive `/intelligence` page now supports launching and observing **explicitly registered repository engineering goals** and applying a previously verified patch in a separate, explicit approval step. This is a controlled Python repository workflow, not unrestricted shell/browser automation.

## Authorize an existing goal from Ubuntu, not the browser

```bash
cd /mnt/hdd16T/ToqeerHomeBackup/toqeer/MioAgent
PY="$HOME/.cache/mioagent/phase1-venv/bin/python"
"$PY" -m scripts.register_repo_goal /var/tmp/mioagent-native-1002/repo-engineering-demo-goal.json
```

Registration takes a **local owner-selected goal** with absolute repository path, 1–4 approved existing source files, 1–6 original `test_*.py` test files, and 1–3 candidate attempts. It stores the immutable contract and hashes of the acceptance-test bytes in a user-owned `0600` file under `/var/tmp/mioagent-native-1002/dashboard-approved-goals`. No model inference or repository writes occur at registration. Model prompts never grant file access or commands.

Open `http://127.0.0.1:13000/intelligence` through your existing Windows SSH local port forward to Ubuntu's `127.0.0.1:3000`. The page header must say `v0.4G DASHBOARD`. After registration, refresh: the goal will appear with its approved edit/test paths.

A goal that was already executed by the v0.4E CLI (like the user's existing demo) will show its passing report and patch. The UI won't replay the same goal because each goal digest can run only once. For a **new** registered goal with a fresh digest, click **Run models and isolated tests**. This launches a detached child with a fixed argv (not shell), stores a private status/log, runs the existing goal through `scripts.repo_engineer.run`, and leaves original files untouched. The UI polls current state, completed tests and bounded logs.

For a passing run, click **Review verified diff** and inspect the exact bytes. The **Approve and reverify application** action requires a second confirmation and the SHA-256 of the displayed patch. The worker then invokes `scripts.repo_engineer.apply_previous`: tests are rerun in Bubblewrap, registered acceptance-test hashes are checked again, candidate/source hashes must match, and exactly the reviewed permitted source files are applied. No model call, Git push, or third-party shell command occurs during approval. A second application or replay is rejected. Original-byte backups are kept in the private run artifact.

## What this does not do

- It does not register arbitrary filesystem paths or install/download models from an HTTP request. Only a trusted workstation CLI can add a contract.
- It does not enable general code execution, browser automation, automatic Git commits, remote compute or paid APIs.
- It does not grant the browser write access to source files outside the contract. Neither the model nor the user's prompt can expand the trusted allowlist.
- No user-controlled command is ever passed to a shell. Execution is the fixed pre-existing Bubblewrap/test workflow.
- Private `/var/tmp` jobs may be cleaned by the OS. A forcibly killed worker can leave a `queued/running` status; this intentionally requires manual investigation rather than silently replaying a partial operation.
- A passing acceptance suite proves only its checked behavior. The operator must still inspect the source diff before applying to a real project.

## Verify dashboard vs Windows tunnel

The native Ubuntu app listens at `http://127.0.0.1:3000/intelligence`. If that is v0.4G but Windows' `http://127.0.0.1:13000/intelligence` is old, it is not a Python model problem. On Windows PowerShell, inspect `Get-NetTCPConnection -LocalPort 13000 -State Listen` and the SSH process that owns it. Only after checking and stopping a **stale tunnel you own** should you recreate `ssh -N -L 13000:127.0.0.1:3000 toqeer@157.27.31.126`. Never terminate unrelated listeners. Refresh with Ctrl+Shift+R.
