# AGENT6B: Owner-controlled multi-step Work preview

**Release status:** Source addition and CLI preview only. It deliberately does **not**
wire into the running API/worker or enable autonomous file/terminal access.

## Execution workflow

1. Owner chooses a concrete goal and explicit repository source files.
2. Deterministic planner classifies `repair` / `implement` / `audit` / `explore`,
   creating a five-stage review plan. No LLM text is executable authority.
3. Read-only inspection uses file-descriptor-relative, `O_NOFOLLOW` reads and
   blocks symlinks, traversal, VCS/private vault, secrets, generated dependencies,
   binary files and oversized source files.
4. Python syntax/definitions are parsed using `ast` **without importing** the code.
5. An exclusive, checksum-verifiable, new JSON receipt is written under
   `.mioagent-private/agents/audit/agent6b/`, never overwriting an existing receipt.
6. Remaining code edits, test runs, services, model suggestions, Git publication
   and permission grants stay blocked pending distinct owner approvals and tests.

## Project and storage boundaries

- `MioAgent` remains the only place for durable new project files and receipts.
- The root-owned 0777 `fuseblk` mount **does not** provide confidentiality or
  tamper-resistant storage. No live tokens or credentials are added to receipts.
- The real production SQLite databases remain in the native legacy runtime.
- VAULT5A 225-file, 85-PNG copy-only checkpoint and AGENT6A accepted native
  regression receipts are preserved.
- No service restarts, destructive cleanup, overwrite, sudo or recursive chmod.

## AGENT6C planned activation gate

After the new bounded preview passes independent regression, add authenticated
Work API and worker integration with separate human-issued task-scoped grants,
real sandbox-executed tests and explicit before/after file manifests. Do not
interpret this AGENT6B preview as authority to enable these features directly.

## Owner preview invocation (after guarded source installation)

`python -m scripts.mioagent_agentic_preview --mode plan-and-inspect --goal 'Inspect the Work engine for safe next phase integration' --approval 'AGENT6B OWNER APPROVES READ ONLY PLAN INSPECT AND AUDIT RECEIPT'`
