# MioAgent v0.3A — Project Mode (reviewable source drafts)

**Status:** integrated developer-preview; workstation build, lint, and real local model smoke are required before enablement. It does not autonomously complete whole projects yet.

## What this milestone actually does

- `GET /api/projects`, `GET /api/projects/{id}`, `POST /api/projects`: create a persistent project and queue one actual local-model call. Projects are separate from read-only Chat Mode.
- Local-only JSON output is parsed into a bounded plan and 1–6 source files, with strict relative path/extension limits and total size <= 64 KiB. Python and JSON content receive *static syntax checks only*. Model output is untrusted even when it comes from the local server.
- Project status changes: `drafting → review → applying → completed`, or `failed/canceled`. No files are written at the draft stage.
- `POST /api/projects/{id}/apply` requires `{ "approved": true }`. This explicit approval saves the exact validated bytes in one unique directory under a user-owned 0700 native Linux root using a private staging directory followed by rename; files are 0600. No reapplication or overwrite allowed.
- The existing task queue persists draft and apply task metadata; interrupted tasks are requeued, and an existing completed artifact is verified byte-for-byte rather than overwritten after restart.
- The `/projects` dashboard shows project status, source preview, and approval controls. The `/assistant` interface remains conversational and does not gain filesystem privileges.
- Cloud API usage is forcibly disabled for project drafting even when the general application might allow cloud. Uses the existing locally configured model; no new GPUs or models are launched, and university GPUs remain unused.

## Not provided yet

Project mode **does not** run model-generated code, install packages, open browsers, execute tests, fetch online resources, commit/push Git, deploy services, select arbitrary repositories, or silently modify existing projects. Syntax checks are not execution tests. The baseline Ollama 20B model is not guaranteed to emit valid JSON or build high-quality programs on its first attempt. If the model fails draft validation, the task fails explicitly; no pretend success or insecure parser fallback.

This deliberately stops short of full Codex/Claude Code behavior until the executor can enforce real OS isolation. Source generation and approval are a first *working* capability, not project-completion autonomy.

## Storage and permissions

Project output defaults to `/var/tmp/mioagent-native-<uid>/projects`, provisioned by the native runtime. It is under native Linux storage and avoids NTFS and SMB/CIFS. The entire root must be owned by the service user, mode 0700, on a recognized native Linux filesystem (ext4/xfs/btrfs/zfs). Individual artifacts are strictly bounded to <= 64 KiB in this preview. The planner policy is not a GPU scheduler: concurrent calls still use the existing local model daemon.

**Critical:** `/var/tmp` may be cleared by reboot, OS policy or housekeeping. This location is suitable for prototyping, **not** the durable long-term project store. Before long-running projects, allocate owner-private persistent ext4/xfs/btrfs (or another reviewed secure filesystem), backup/export workflows, quota enforcement, and monitoring. Do not point `MIO_PROJECT_ROOT` at the NTFS/FUSE source tree or KIOS CIFS share. The current runtime also keeps SQLite data under `/var/tmp`, which separately needs a persistent native volume before production hardening.

## Enable only after workstation tests

The new feature remains OFF after installation. Once workstation tests and dashboard build pass, from the project root:

```bash
python3 -m scripts.project_mode_control enable
python3 scripts/native_runtime.py stop
python3 scripts/native_runtime.py start
python3 scripts/native_runtime.py smoke
```

Stop/start is an explicit operator action; the installation script does not restart services. `python3 -m scripts.project_mode_control disable` followed by a controlled restart disables new requests. The flag is an owner-only regular file; the runtime overrides inherited `MIO_ENABLE_PROJECT_MODE` and `MIO_PROJECT_ROOT` values. The feature and API stay bound to the workstation's `127.0.0.1` backend by default.

To test Project Mode, open `http://127.0.0.1:13000/projects` from the laptop when SSH local forwarding is active. Try a small Python task; review generated source; explicitly approve. Inspect output via the workspace path from `GET /api/projects/{id}`. Do not assume the generated program works until it has been run in an appropriate isolated environment.

## Vercel safety

The existing Next.js proxy carries a privileged bearer token on the server and **is not safe to expose anonymously**. With the `VERCEL=1` environment variable present, the updated proxy returns HTTP 503 for ALL proxied API calls, even if backend credentials happen to be configured. This means a Vercel website may show the UI but cannot issue live AI or project commands yet. Making it function online requires end-user authentication, authorizations scoped to actions and projects, CSRF/origin protection, rate limiting, a secure private workstation bridge, audit logs, and independent penetration/security review. Vercel is *only* a frontend host, never the persistent GPU inference backend.

## Verification gates

The package includes unit and API integration tests against a stub model (no downloads or real GPU calls). Before a push, run full Python tests, Ruff, dashboard typecheck/build, backend smoke, then one *real model* end-to-end project draft. The original Phase 2 dashboard routes and native runtime smoke must continue passing. Review the complete Git diff and exclude credentials, model data and private project artifacts. Publish only on user approval and a clean workstation status.
