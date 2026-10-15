# Phase 1 acceptance checklist

- [x] Master plan version 1.0 documented in repository content.
- [x] Workstation inventory summarized from user-supplied command output.
- [x] Backend application, SQL persistence and restricted demo worker authored.
- [x] Dashboard implementation authored with real API status, queue and cancel views.
- [x] Docker Compose, dev tests, CI and security docs authored.
- [ ] Confirm actual filesystem type/ownership and Docker Compose availability on workstation.
- [ ] Unpack/copy files to workstation directory.
- [ ] Generate private credentials locally under `~/.config/mioagent/.env`.
- [ ] Run backend tests and frontend typecheck/build successfully on workstation.
- [ ] Start Docker Compose and verify dashboard/API health locally.
- [ ] Run `python3 scripts/smoke_test.py` and a real workflow from dashboard; observe persisted status.
- [ ] Reboot/restart test for task persistence (safe idempotent task).
- [ ] Review `.gitignore`, staged change list and secrets before publishing.
- [ ] Initialize Git locally, connect to GitHub, commit and push milestone.

**Status:** Source package prepared, deployment not yet executed on workstation. Check items only after verification. A ready-to-import archive is not evidence of successful host installation.
