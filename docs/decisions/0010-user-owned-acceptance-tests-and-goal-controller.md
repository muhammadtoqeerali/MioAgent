# ADR 0010 — Goal-driven supervisor with owner-authored immutable acceptance tests

Date: 2026-10-19. Status: ACCEPTED for a guarded local preview, pending full workstation release and live exercise.

## Context

The existing local agent has a model gateway, generated draft projects, Bubblewrap Python unittest verification, bounded source-only repair and a metadata capability catalog. These are useful but disconnected. Model-generated tests may omit acceptance cases or weaken success criteria. The user's primary goal is agent intelligence and execution capability; defer further backup enhancements after the first KIOS off-machine encrypted archive was independently verified.

## Decision

Add an operator-only `goal.json` supervisor with task-role planning, local model routing policy and a single accountable create/draft/approve/test/repair flow. A new authenticated API route accepts owner-supplied `test_*.py` sources **only while a project is awaiting source approval**; it atomically replaces model tests, validates source hashes and all file policies and persists reviewed draft metadata. Existing test immutability protections apply after approval. An opt-in CLI flag delegates only the bounded approved workflow, never shell/browser/network/Git rights. One local model, no unapproved downloaded skills or paid calls.

## Consequences

A meaningful small-project end-to-end controller becomes possible without duplicating workspace or sandbox code. More API surface and one controlled service restart are required. The trusted user must define useful tests; passing weak tests cannot establish quality. Persistent reporting, a genuinely independent reviewer, safe developer-tool execution, richer models/skills, functional dashboard integration, and robust recovery remain future work. No change to locked master plan, native runtime secrets, or university compute policy.
