# MioAgent v0.3F — Offline private integrity snapshots (first durability gate)

## What is implemented

A new additive `python -m scripts.durable_storage` CLI can inspect the **current**
SQLite/project-artifact footprint, initialize a user-private backup directory
on a native Linux filesystem, take an **offline** verified snapshot, and verify
an existing snapshot against SHA-256 hashes and SQLite `PRAGMA quick_check`.
The program is a safety tool, not yet a runtime-directory migration.

**No live services are modified or restarted by the installation.** The CLI
refuses a snapshot while MioAgent's managed API or dashboard is running. Each
snapshot is constructed inside the chosen private destination and atomically
renamed only after complete verification; a failure removes its incomplete copy.
Existing snapshots and original files are never deleted. A `--max-mib` budget
(default 2048 MiB) prevents unexpectedly large copies. There is no automatic
retention cleanup or scheduling in this release.

The CLI copies only:

- `data/mioagent.db`, via SQLite's online-compatible Backup API while services
  are required to be stopped, then checks its integrity;
- regular files from `projects/`, with size/ownership/symlink guards and SHA-256
  hashes, with relative paths preserved.

The CLI deliberately **excludes** `api-token`, `model.env`, service flags,
process files, and logs. **Project records themselves may contain private
requirements, user text and code:** snapshots are not encrypted in this
release. Do not sync them to public GitHub, Vercel, shared folders, university
storage, or cloud drives. The destination must be a user-private `0700`
directory on verified ext4/xfs/btrfs/zfs/f2fs; no NTFS/FUSE/CIFS, tmpfs, `/tmp`,
`/var/tmp`, `/run`, or writable-by-other-users storage.

## Why migration is not automatic

The workstation's `HOME` and Git checkout are on an NTFS/FUSE volume; the
current private runtime is under `/var/tmp/mioagent-native-1002` on ext4, which
is not durable against system cleanup. Although the `/` partition has free
space, no long-term **user-owned, writable ext4 directory** has yet been
verified. Migrating blindly into `/var/tmp`, a shared mount, or an
administrator-owned path would risk data loss or secrets. This milestone lets
us inspect existing data and produce recoverable snapshots after a valid
permanent location is selected.

## Installation / audit (no interruption)

```bash
cd /mnt/hdd16T/ToqeerHomeBackup/toqeer/MioAgent
VENV="$HOME/.cache/mioagent/phase1-venv"
"$VENV/bin/python" -m scripts.durable_storage audit
findmnt -t ext4,xfs,btrfs,zfs,f2fs -o TARGET,SOURCE,FSTYPE,OPTIONS
```

Choose a **permanent** writable native Linux filesystem path. You may need an
administrator to create a directory owned by your Unix user. Do not use
`/var/tmp`, your NTFS checkout, university CIFS storage, or a publicly
accessible web directory. Then, for example, with your *actual approved path*:

```bash
DEST=/verified/permanent/native/linux/path/mioagent-backups
"$VENV/bin/python" -m scripts.durable_storage init --destination "$DEST"
"$VENV/bin/python" scripts/native_runtime.py stop
"$VENV/bin/python" -m scripts.durable_storage snapshot --destination "$DEST" --max-mib 2048
"$VENV/bin/python" scripts/native_runtime.py start
"$VENV/bin/python" scripts/native_runtime.py smoke
```

**A placeholder path must be replaced, not pasted unchanged.** If the snapshot
fails, run the runtime `start` command separately after investigating the
failure; the CLI itself never automatically restarts a service. The source
is never modified. For any snapshot, validate it again with:

```bash
"$VENV/bin/python" -m scripts.durable_storage verify /absolute/path/to/snapshot-folder
```

## Recovery and next stage

The snapshot directory has `manifest.json`, `data/mioagent.db`, and `projects/`
files. A restore operation is intentionally **not automated** yet. Before a
restore/migration, stop services, back up originals, validate the manifest and
SQLite integrity, perform a trial restore into an independent directory,
check the database's `projects.workspace_path` references, and atomically
switch the runtime root with a rollback option. Paths embedded in the SQLite
project rows currently refer to the original `/var/tmp/.../projects` tree;
blind copying a database into a new runtime root is **not sufficient** to
restore a working application. A migration of those paths requires its own
tested release with explicit data checks.

## Known limitations

- An offline snapshot is not automatically scheduled, nor tested as a full
  application restoration. A passing hash check is **not** proof of a usable
  restored MioAgent instance.
- Existing `ModelRouter`, Vercel proxy and GPUs are untouched.
- No backup encryption, snapshot pruning or automatic migrations yet.
- Operator should keep the runtime stopped for the entire offline snapshot;
  the process-PID safety check covers known MioAgent services, not all possible
  external writers.
- Requires a permanent ext4 location with proper ownership. Without it,
  use `audit` only; do **not** move current data.

## Next acceptance gate

1. Verify an approved, permanent ext4 user-storage location.
2. Take an offline snapshot and re-check all hashes and SQLite integrity.
3. Build a migration tool with explicit project-path rewriting, dry-run,
   fail-safe rollback, service restart smoke checks and a real restore drill.
4. Only then add scheduled backups and quota-controlled retention.
