# ADR 0007 — Test-grounded, immutable-source repair proposals

- **Status:** proposed, bounded implementation for v0.3C
- **Decision:** Test failures trigger a local-model repair *proposal* only on an explicit authenticated action. Accept only replacement text for existing non-test Python source files. Build a complete draft by merging unchanged, hash-preserved original files and tests. Promotion creates a **new** review-only Project; original approved bytes are never overwritten, and new revision execution still requires explicit Bubblewrap test approval.
- **Why:** Local model output is untrusted and may weaken its own tests, invent execution results or produce unsafe files. Immutable tests and an independent verified runner make genuine improvement measurable. Review gates are appropriate until a more capable executor and security hardening exist.
- **Resources:** Use existing single Ollama model; no new GPU or cloud dependency. The durable worker queue is already sequential.
- **Consequence:** Not Codex/Claude Code parity; only one proposal per failed project, intentionally small scope and human decisions. Keep the Vercel remote API disabled until authentication and private connectivity are separately reviewed.
