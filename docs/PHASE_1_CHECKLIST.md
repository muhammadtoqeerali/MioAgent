# Phase 1 acceptance checklist

- [x] Master plan version 1.0 documented in repository content.
- [x] Workstation inventory summarized from user-supplied command output.
- [x] Backend application, SQL persistence and restricted demo worker authored.
- [x] Dashboard implementation authored with real API status, queue and cancel views.
- [x] Docker Compose, dev tests, CI and security docs authored.
- [x] Confirm project filesystem type/ownership (`fuseblk`, `root:root`, `777` on NTFS/FUSE); see `docs/PHASE_1_REPAIR.md`.
- [ ] Confirm Docker Compose availability and security of credential-file filesystem with `python3 scripts/phase1_doctor.py`.
- [x] Unpack source to workstation directory (verified by uploaded terminal output).
- [x] Generate local credentials at `~/.config/mioagent/.env` (verified by terminal output).
- [ ] Review/migrate credential storage because `$HOME` appears to be on an NTFS/FUSE volume.
- [ ] Run backend tests and frontend typecheck/build successfully on workstation.
- [ ] Start Docker Compose and verify dashboard/API health locally.
- [ ] Run `python3 scripts/smoke_test.py` and a real workflow from dashboard; observe persisted status.
- [ ] Reboot/restart test for task persistence (safe idempotent task).
- [ ] Review `.gitignore`, staged change list and secrets before publishing.
- [x] Initialize Git locally and stage initial files (verified by terminal output).
- [ ] Correct all lint/Git whitespace errors, re-stage, confirm GitHub origin, commit and push milestone.

**Status:** Workstation install initially stopped on Ruff lint. Git initialized/staged, but whitespace check failed. A repair is prepared; frontend Docker and smoke verification are still pending. Check items only after verification. A ready-to-import archive is not evidence of successful host installation.
