# ADR 0009 — Encrypted offline export with Windows VPN relay

**Status:** Proposed for guarded v0.3G rollout, 2026-10-19.

## Context

The workstation cannot resolve the university KIOS SSH host directly. University VPN is accessible from the user's Windows laptop. The user lacks sudo and a suitable permanent owned Linux directory on the workstation. KIOS personal home uses a shared XFS root with limited free space; its user storage is CIFS, not appropriate for active SQLite.

## Decision

Use an **operator-initiated encrypted backup archive**: stop local services after checking no active jobs, make a verified offline SQLite/project snapshot, encrypt before storing on the NTFS volume, verify ciphertext locally, and restart services. Only the ciphertext is ever transferred through Windows over the existing VPN. Do not sync secrets/configuration. KIOS storage and account use must be approved by site policy; zero remote GPU or service usage.

## Consequences

This provides an encrypted off-host recovery copy once transport succeeds, but not persistent active SQLite, unattended scheduled backups, automatic recovery, or protection against loss of the encryption passphrase. An ephemeral plaintext SQLite staging copy briefly exists on the workstation. Retention and recovery testing remain future work.
