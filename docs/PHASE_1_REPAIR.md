# Phase 1 troubleshooting and remediation — 2026-10-15

## Recorded workstation findings

- Ubuntu 22.04.5; Ryzen 9 7950X (16 cores, 32 threads); 187 GiB RAM; two RTX 4090 GPUs; approximately 12 TB free.
- Project path is on `/mnt/hdd16T` with filesystem reported `fuseblk` (NTFS/FUSE). Files show `root:root` and mode `777` regardless of author intent.
- Local Python tests: **2 passed**, one unrelated Starlette/httpx deprecation warning.
- The original install stopped at Ruff with `EXE002`, `UP017`, and `BLE001`; therefore npm build, Docker Compose deployment, and smoke test are **not yet confirmed**.
- Original Git repo was initialized, files staged, then `git diff --cached --check` failed on Markdown trailing spaces and a blank line at Python EOF. No successful push was reported.

## What the repair changes

1. Use `datetime.UTC` in Python 3.12+ code.
2. Keep worker exception reporting while explicitly suppressing Ruff `BLE001` at that recovery boundary.
3. Ignore Ruff `EXE002` because NTFS/FUSE reports Python source as executable; normalize Git index bits separately.
4. Remove staged trailing whitespace and blank EOF; add TypeScript incremental build output to `.gitignore`.
5. Clarify secret-storage limitations; do not treat a path outside the repo as secure when `$HOME` is also on NTFS.
6. Add a read-only host check: `python3 scripts/phase1_doctor.py`.

## Important security observation

The generated credentials path in your output is `/mnt/hdd16T/ToqeerHomeBackup/.config/mioagent/.env`. Since `/mnt/hdd16T` is NTFS/FUSE mounted with `allow_other`, a displayed `0600` file mode is not reliable evidence that other local OS users cannot read it. Do **not** push that file, share it, expose the dashboard to remote networks, or grant sensitive system access based on that assumption.

For stronger protection choose a user-owned directory on a genuine native Linux filesystem (for example an administrator-provisioned directory on ext4) and pass its credential file with `docker compose --env-file <secure-path>`. Do not assume `/home` is a separate secure filesystem; verify using `findmnt` first. Rotate credentials after moving them if any other user could have read them.

## Validation before GitHub

Run Ruff, tests, dashboard typecheck and production build, Docker Compose validation/start, smoke test and finally `git diff --cached --check`. Review the staged file names, ensure `.env` and caches are not tracked, and only then commit/push. Use `git config core.filemode false` for this NTFS/FUSE checkout and normalize Python source mode in the **index** with `git update-index --chmod=-x` after staging.
