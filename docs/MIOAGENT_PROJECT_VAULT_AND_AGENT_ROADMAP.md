# MioAgent project-contained storage and agent execution plan

## Owner-selected root

`/mnt/hdd16T/ToqeerHomeBackup/toqeer/MioAgent`

All **new permanent** private data belongs under `.mioagent-private/` in this
repository and must never be published to Git. The folder is owner-only `0700`,
containing private `0600` files. It is not a substitute for off-machine backups.

### Layout

- `data/chat/` — future live Chat database cutover
- `data/work/` — future live Work database cutover
- `studio/omni-images/` — persistent image copies and future live image store
- `studio/attachments/`, `studio/jobs/` — future live Studio cutover
- `projects/` and `workspaces/` — managed project and output workspaces
- `artifacts/` — generated documents, reports, images, exports
- `agents/grants/` — owner-authorized expiring capability grants
- `agents/workspaces/` — isolated per-session files; no access to other paths
- `agents/audit/` — append-only action/evidence logs (future wiring)
- `backups/` — verified historical native-runtime snapshots
- `state/` — private source/storage receipts and future migration markers

## VAULT5A actual scope

1. Adds secure filesystem and online SQLite snapshot helpers.
2. Creates an immutable project-local snapshot of managed `/var/tmp` runtime
   (Chat/Work databases using SQLite's live backup API, plus Studio/Work/projects
   files and supported private config state). No legacy data deleted or changed.
3. Copies existing image PNGs to their future permanent project location.
4. Implements expiring, session-scoped permissions and a small set of bounded
   tools. These are not yet exposed to model-generated Work tasks.
5. Rejects symlinks, path traversal, overwriting existing workspace files, and
   unsupported direct shell, laptop, remote and publishing capabilities.

**Important**: During VAULT5A, the actively running API, Work worker, Ollama and
ComfyUI retain their previously configured runtime directories. A snapshot is
not a live-storage cutover; new data written after the checkpoint needs another
synchronized copy. No service restart occurs in this phase.

## VAULT5B: coordinated live storage migration

A later approved release must atomically coordinate the supervisor, API,
Chat/Work databases, Studio attachments/jobs, image store and Work worker:

1. Stop intake of new jobs and wait for each queue to be idle.
2. Create a fresh project-contained online DB snapshot and verify all private
   file manifests with checksums, owner and permissions.
3. Switch all runtime data roots together, while preserving the old location as
   rollback-only; then restart only managed processes.
4. Verify new image creation/editing, standard Chat, Projects, Work, uploads,
   archived history, and persistence across restart. Never delete old files.
5. Ensure every new artifact is written below the owner-selected project root.

Model weights, installed Python environments and independent Ollama/ComfyUI
services require their own separately gated relocation plan before claiming
**all software resources** are fully contained under the project tree.

## Agent milestones

- **TOOLS5A:** opt-in project-read, workspace-create, bounded tests and local
  health checks. Persistent grants expire after a maximum of seven days; only
  the owner can issue/revoke them through a local interactive terminal.
- **TOOLS5B:** connect these capabilities to Work as explicit typed tools,
  with full audit logs, kill switch, cancellation, resource budgets and review.
- **AGENT6:** multi-step planning/execution/evaluation with durable checkpoints
  and retry handling. Source/code self-improvements must use disposable
  worktrees, pass tests and await separate human approval before merging.
- **REMOTE6:** secure mutually authenticated and owner-paired laptop connector,
  with per-device scopes, revocation and strict boundaries. No inbound LAN
  listening or network credentials are silently enabled.
- **SKILLS6:** owner-reviewed versioned skill packs for coding, research,
  scientific tasks, writing and design. Skills are instructions/data, not
  permission to bypass tool governance or import third-party credentials.

Never automatically run broad host shell commands, delete user data, grant
remote access, change Git remotes, force-push or silently deploy unreviewed code.

## Root-owned 0777 checkout without sudo (Recovery3)

When the exact project directory is root-owned and mode 0777, a one-time
**explicitly authorized, checkpoint-only** compatibility mode can create a
0700 user-owned `.mioagent-private` directory beneath it. Files in that
directory are mode 0600 and checksummed, and the running services remain on
their existing storage. **This is not a fully secure persistent runtime
configuration**: any other local user with access to the world-writable parent
can rename the private directory (denial of service and possible path-swap
attack). The controller checks identity and never activates a live vault under
that parent. This mode deliberately omits API credentials from the checkpoint.

Only an administrator or filesystem owner can fix the parent directory's
ownership/permissions. Do not treat the compatibility mode as a substitute.
There is no sudo, no owner change, no chmod on project root, and no change to
any path outside the project during this release.


## Recovery4: NTFS/FUSE no-sudo compatibility checkpoint

The MioAgent checkout is hosted on an NTFS/FUSE volume (confirmed by the
published pyproject comment). Its root is UID 0, mode 0777 and cannot be
reowned without administrator privileges. On some mounts, `mkdir(0700)` and
`open(0600)` report synthetic modes instead of enforcing private Unix access.

The **provisional compatibility checkpoint** is allowed only after exact
root/branch/hash approval and a read-only `findmnt` probe plus controlled
filesystem mode probe. It stores files inside the MioAgent checkout, uses
exclusive creation, rejects symlinks, protects source integrity with SHA-256,
uses SQLite's online backup API, and never edits the active runtime. It does
**not** claim OS-enforced confidentiality: a local host administrator may
access storage, and other accounts may have access under mount permissions.
No private API credential/key is copied by this recovery.

Persistent grants, external tools, autonomous Work wiring, and active SQLite
cutover stay disabled on this mount. The checkpoint is not encrypted and
is not a substitute for independent or offline backup. Use an approved
filesystem/container format with strong encryption or a privately controlled
mount if confidential storage is later required. No sudo is used here.
