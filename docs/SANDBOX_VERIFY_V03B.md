# MioAgent v0.3B — Guarded Python unittest verification

## Exact capability delivered

An approved Project Mode source artifact may be **separately** submitted for Python `unittest` execution in an experimental Linux Bubblewrap sandbox. AI draft generation, explicit approval to write source, and explicit approval to run tests are distinct transitions. This release **does not grant a coding model shell access**. No model-generated command is ever accepted. The sole executed command is a fixed system Python interpreter running a fixed, administrator-authored `unittest` harness.

`POST /api/projects/{id}/verify` with `{"approved":true}` queues a durable `project_verify` task. `GET /api/projects/{id}/verification` reads the newest task and result. API bearer authentication and Project Mode guards are unchanged. The verifier is additionally disabled unless an owner-private `sandbox-verify-enabled` flag was set using the CLI after a live Bubblewrap preflight. The private backend remains bound to loopback; Vercel proxied API access remains blocked.

The verifier uses the approved draft and checks that the previously approved artifact matches its original hashes. It copies **only approved, hash-matching bytes** to an ephemeral, user-private staging directory on the native filesystem. It never mounts the Git repository, home, NTFS volume, university CIFS share, workstation model weights, GPU nodes, or API credentials. The approved original is read-only and unchanged.

The execution container uses unprivileged user/PID/network/IPC/UTS namespaces, dropped capabilities, an otherwise empty root filesystem, read-only `/usr`, a read-only `/work` staging mount, a read-only `/tmp` directory, and a proc/dev minimal mount. The trusted harness has 12 seconds CPU, 768 MiB address space, 2 MiB max individual file, 64 file descriptors, a low per-UID process limit, 30 seconds wall time, and 32 KiB captured output. The existing single-worker queue ensures only one verification task runs at a time. Temp files are cleaned up after the task. A broken/missing Bubblewrap preflight fails closed; no host execution fallback exists.

**Warning:** Bubblewrap is useful isolation, not a substitute for kernel patching, independent security review, host policy, or deployment hardening. Namespace availability alone is not enough; actual launch must succeed. We did not benchmark hostile adversarial programs. Do not run externally supplied exploit samples.

## Python testing scope

The initial harness supports **Python standard-library `unittest`** with `test_*.py` files in the approved draft. No shell commands, `pytest`, arbitrary `requirements.txt`, packages, browser access, pip/conda install, database services, or arbitrary entry points are enabled. The original Python sources are mounted read-only: tests requiring temporary writes fail by design in this initial read-only verifier. Missing tests report `no_tests` and `passed=false`, rather than claiming success. Test failures report `passed=false` with captured output and return code. Output is diagnostic and may be affected by untrusted code; human review remains mandatory.

This is intentionally **not yet auto-repair** or complete Codex/Claude Code autonomy. Next step is bounded source patch proposals (without silently editing approved output) followed by reapproval and independent retesting.

## Workstation activation / rollback

Run installer and release gates first; it leaves execution **disabled**. After validation and operator review, on the workstation:

```bash
VENV="$HOME/.cache/mioagent/phase1-venv"
"$VENV/bin/python" -m scripts.sandbox_verify_control probe
"$VENV/bin/python" -m scripts.sandbox_verify_control enable
"$VENV/bin/python" scripts/native_runtime.py stop
"$VENV/bin/python" scripts/native_runtime.py start
"$VENV/bin/python" scripts/native_runtime.py smoke
```

Local dashboard at `http://127.0.0.1:13000/projects` now permits a second, explicit **I approve sandbox test execution** action on a previously approved project. Only projects containing `test_*.py` will run unit tests.

To disable new runs:

```bash
"$VENV/bin/python" -m scripts.sandbox_verify_control disable
"$VENV/bin/python" scripts/native_runtime.py stop
"$VENV/bin/python" scripts/native_runtime.py start
```

In-flight tasks can take up to their 30-second hard time limit. The Vercel site can show the new frontend after the commit but cannot connect to your private model until the independently designed secure bridge and authenticated sessions are implemented.

## Storage and hardware budget

No additional model is downloaded. Verification itself uses **CPU only**, relies on your existing Ollama model solely for drafts, and does not touch KIOS V100s or network storage. Per run, source draft is <=64 KiB, the sandbox permits no writable filesystem, captured output is <=32 KiB, with ephemeral staging cleaned up. Persistent task records accumulate over time; database retention and backups are a separate milestone. Runtime is under `/var/tmp`, subject to OS cleanup, not yet durable storage.

## Legacy Bubblewrap compatibility (v0.3B.1)

The original v0.3B relied on `bwrap --size 16777216 --tmpfs /tmp`; the
workstation's installed `bwrap` rejected `--size`. The verifier now builds a
throwaway root mount and remounts its root, `/proc`, and `/dev` read-only; `/tmp`
is also read-only. It deliberately does **not** fall back to an unrestricted
writable tmpfs. Pure Python `unittest` suites work, but tests using filesystem
writes, `tempfile`, or SQLite will fail: this is an intentionally limited
first executor. Writable, size-bounded scratch storage requires a future
separately tested kernel/cgroup or upgraded Bubblewrap implementation.

The preflight now rejects the sandbox unless the filesystem mount flags for
`/`, `/tmp`, `/dev`, `/proc` and `/work` are all read-only. It does not need to
create even a harmless test file to prove the restriction. No code from unapproved projects runs.

## Ubuntu alternatives compatibility (v0.3B.2)

The workstation uses `/usr/bin/python3 -> /etc/alternatives/python3 ->
/usr/bin/python3.10`. Earlier versions validated the final binary but passed
`/usr/bin/python3` as the executable path to Bubblewrap. The sandbox does not
mount `/etc`, so `execvp` could not resolve that symlink, resulting in
`No such file or directory`.

The verifier now passes the **resolved, root-owned `/usr/bin/python3.10` path**
(or its equivalent on other Linux hosts) after validating it lives under
`/usr` and is not group/world-writable. It does not expose `/etc`, expand
filesystem access, grant network privileges or run project code as part of
preflight. The full live Bubblewrap probe remains mandatory before install.
