# Dashboard troubleshooting: local vs remote browser

MioAgent Phase 1 listens on **127.0.0.1 only**, for both the API (`8000`) and web UI (`3000`). This is intentional. `127.0.0.1` belongs to the **computer running the browser**, not necessarily to the development workstation.

## What was fixed

Next.js 16 can rename the live dashboard process to `next-server (v...)`. Earlier `native_runtime.py status` checked only the original Node command line, incorrectly reporting `dashboard: not running` while an HTTP 200 response proved the server was active. Process recognition now verifies recorded PID, OS user, exact working directory, and Node executable when accepting the renamed title. It does **not** terminate arbitrary port 3000 processes.

## Read-only diagnostic

From the workstation terminal:

```bash
python3 scripts/dashboard_doctor.py
python3 scripts/native_runtime.py logs
```

- If the workstation diagnostic says PASS but the screenshot browser says `ERR_CONNECTION_REFUSED`, verify whether the browser is on a different computer, container or network namespace. Try opening the dashboard from the workstation's own desktop session.
- The UI is `http://127.0.0.1:3000/`; `http://127.0.0.1:8000/health` is **API health**, not the dashboard.
- Use HTTP GET for `/health`; `curl -I` uses HEAD, which the API may reject with 405 even though GET is healthy.

## Secure access from another computer

If your **workstation already has SSH server access available** (no sudo installation instructions), run **on the computer where the browser is located**:

```bash
ssh -N -L 3000:127.0.0.1:3000 YOUR_SSH_USER@WORKSTATION_HOST
```

While that SSH connection remains open, browse to `http://127.0.0.1:3000/` on the viewing computer. **Do not bind MioAgent's bearer-token-protected API to `0.0.0.0` or expose port 8000 to the LAN.** If SSH is not available, consult the workstation administrator for an approved remote-access solution.

## Restart only when needed

After updating this runtime source and passing tests:

```bash
python3 scripts/native_runtime.py stop
python3 scripts/native_runtime.py start
python3 scripts/native_runtime.py smoke
python3 scripts/native_runtime.py status
```

This may briefly interrupt only MioAgent-owned services; task records and the API token remain in the existing runtime directory.
