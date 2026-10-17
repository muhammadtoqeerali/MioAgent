# ADR 0008 — Stage durability behind offline verified snapshots

Status: PROPOSED (implementation of snapshot gate, no runtime migration)
Date: 2026-10-17

## Context

The native MioAgent runtime stores SQLite, approved projects and authentication
flags under `/var/tmp` on ext4. The workstation's home and Git directory are
on NTFS/FUSE, which does not offer the Unix permissions our existing security
controls require. Temporary runtime storage can be cleaned by the operating
system and is not an acceptable long-term store for autonomous projects.

## Decision

Build an offline, additive snapshot tool requiring private native Linux storage
selected by the owner. Only SQLite (using its Backup API) and approved project
artifacts are copied, followed by SHA-256/SQLite checks. Never implicitly copy
secrets, move the runtime, prune snapshots, expose ports, or allocate GPUs.
Existing services must be stopped for a consistent artifact copy. Backup
location discovery and runtime migration remain separate explicit steps.

## Consequences

We gain a bounded, verifiable data-preservation primitive with no changes to
running services. We do **not yet** claim durability: snapshots must land on a
verified permanent filesystem, and restore/migration needs project workspace
path rewriting, own review, a restart test and rollback. Backups are private
but unencrypted; operators must not put them on shared/cloud storage.

Related: `docs/MASTER_PLAN.md`, `docs/MIOAGENT_UNIFIED_INTELLIGENCE_ROADMAP.md`.
