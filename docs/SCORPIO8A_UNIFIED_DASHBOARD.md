# SCORPIO8A — Unified dashboard and project discussions

## Scope

This release keeps a single persistent Scorpio application frame (scorpion mark, global sidebar, local status top bar and footer) across existing Chat, Projects, Work and Control Room routes. It adds real backend-backed Approvals, Tools & Permissions, System Health, Logs & Events and Settings pages. It reuses the existing Chat composer, conversation history, file attachments, image generation, Work assignment forms, worker run history and Scorpio7A owner-reviewed new-run action. It does not replace these APIs.

**All status numbers originate from authenticated Work records.** A responsive API is *not* proof that the worker, ComfyUI or GPU is healthy. Health indicators report only what is actually measured. No fabricated resource utilization or fictitious approval tickets. No service/restart/grant controls are offered without enforceable backend routes.

## Project discussion threads

The current Work database does **not** have a first-class independent thread entity. Project chats in SCORPIO8A use a validated, versioned thread identifier and title embedded in the saved Work run prompt. A separate chat is created with the **New chat** button and becomes durable after its first message. Thread history is reconstructed from real project Work runs; each thread renders only its own messages and recent replies, while retaining common project instructions, approved memories and linked files. The latest 3 turns of that specific thread are included as bounded, visible contextual text to the model when submitting another turn.

**Important limitation:** This is logical project-thread grouping over a shared project Work history, not a server-side thread namespace or guaranteed separate context window. Older project messages predate threads and appear in **Main discussion**. A dedicated backend thread table, per-thread orchestration checkpoints and first-class project-associated Chat history are future migrations requiring separate tests and owner permission. No hidden localStorage session is used to misrepresent durability.

## Approval / attention semantics

A Work state of `needs_review` is a finished, reviewable run, not necessarily a tool authorization request. A real operator panel displays recorded evidence and can submit an explicitly approved **new bounded follow-up** or **new read-only inspection**. It never claims to resume interrupted state or grant new host permissions. `Not now` only closes a panel; it is not durable denial and is not labeled as such.

## Deployment and safety

- Published Git HEAD baseline: `7eb2bfd3b91003f242348d6ff0235bcf474192fd`.
- The controller installs UI sources only, without sudo, service restarts, database migration, live Work tasks, Git commit/push or model grants.
- It rejects unexpected unstaged Git paths, staged content, unapproved source changes, symlinks, wrong checkout, invalid ZIP hashes and non-pinned source bytes.
- Workstation runs `npm run typecheck`, Ruff, focused source contracts and the full Bubblewrap native-memory pytest suite excluding the one separately executed root-executable host trust test.
- The published 11 unrelated worktree paths remain entirely untouched.
- Acceptance and selective publication are separate from the previously tested dashboard-only deployment controller. **Do not rerun the SCORPIO7B deployment controller** after SCORPIO8A publication: that older controller pins a different Git baseline and source manifest. A new SCORPIO8B deployment should be prepared with independent authorization, build backup, identity checked restart and rollback.

## User verification checklist (after guarded dashboard-only deployment)

1. Visit `/control-room` and then `/chat`; confirm the Scorpio sidebar/top bar stay in place.
2. Open Chat, create a conversation, view saved history, use attachments and image creation with existing permissions.
3. Open `/projects-space`; create a project, upload a file and add explicit memory. Select **New chat** and send two messages; confirm thread history survives browser reload, and **Main discussion** remains separate.
4. Open `/work-mode`; create bounded work, inspect live worker audit; open `/approvals` to review only actual needs-review/failed/interrupted runs and submit a new follow-up after an explicit checkbox.
5. Open `/tools-permissions`, `/system-health`, `/activity`; verify measured data and unavailable tool capabilities cannot be toggled.
6. Confirm existing API/Work worker/ComfyUI PIDs, Git staging and 11 unrelated file digests were preserved.

Do not assert that older chats support independent backend-thread isolation, or that unimplemented host controls are enabled.
