# ADR-0006 — Isolate approved unit tests before enabling autonomous tools

**Status:** accepted for workstation prototype; gated by real bubblewrap probe and an explicit user action

MioAgent will not execute AI-generated shell scripts, browse with a privileged session, or write outside its approved artifact root. v0.3B supplies a fixed Python `unittest` harness inside a fail-closed Bubblewrap sandbox on the workstation's private ext4 filesystem. Each test invocation requires approval distinct from source approval. The isolated verifier does not obtain GPU access or contact paid APIs. Host-based command execution has no fallback. Vercel remains a protected frontend shell only.

The fast, cheap path remains Chat Mode. Project Mode adds measurable artifact verification, then later bounded iteration. University shared GPU access and network CIFS storage are left unused pending authorization and an approved quota.

Risk accepted: the first verifier is Linux-specific, supports only standard-library unittest, can fail if local kernel/AppArmor restricts namespaces, and is not a full untrusted-code sandbox security audit. Only clear operator-enabled source execution is permitted. No claims of Codex/Claude parity from this addition.


Compatibility amendment: the first executor uses a fully read-only sandbox,
without the optional `bwrap --size` feature. This limits test suites to those
that do not write files. Preflight verifies the filesystem cannot be written.


### Compatibility follow-up (2026-10-16, v0.3B.2)

Ubuntu's `/usr/bin/python3` may cross `/etc/alternatives` symlinks. Resolve the
trusted system executable before sandbox entry rather than mounting `/etc`.
No relaxation to read-only mounts, offline namespaces, or approval gates.
