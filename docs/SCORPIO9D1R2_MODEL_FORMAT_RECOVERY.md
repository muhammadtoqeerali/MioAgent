# SCORPIO9D1R2 — Bounded coding response-format recovery

Baseline: accepted live SCORPIO9D1 `8bad3fca1a69affa34eac7a37022d1eb2c5b84d0`.

## Evidence prompting this repair

Owner-approved engineering run `945b9f7d36684d078ace79c7d63f1ec0` reached the local coding model twice. Both outputs failed the strict JSON parser (`validation.reject: Coding model did not return valid JSON`); the run ended `failed` without a sandbox attempt or saved engineering artifact. Two subsequently requested follow-ups were **research**, not engineering; they cannot count as engineering acceptance. The raw coding-model responses were not saved, so their exact syntax is unknown. This release addresses common plain/fenced Python formatting while recording sanitized format information. It does not claim to know that the original model used one of these formats.

## Narrow policy

The existing owner-authorized text-utilities prefix `SCORPIO9D1 TEXTUTILS: ` is still mandatory. With it, if the local coding model returns a single syntactically valid plain Python module, or exactly one fenced Python block, the platform treats its *contents as untrusted data* and transforms them into the existing `{"files":[{"path":"textutils.py","content":"..."}]}` envelope. Exactly one `textutils.py` file is synthesized; no model-selected path, uploaded file, shell command, generated test, permission or host side effect is authorized. Other engineering profiles retain their original strict JSON behavior. A single fenced JSON block is unwrapped but must still satisfy existing strict schema validation.

Every candidate continues through the original `parse_draft` syntax/name/size checks, the exact platform-authored 13 acceptance tests, the preflight-verified read-only Bubblewrap sandbox, and the two-response maximum (one bounded repair). The independent result, not the model's assertion, determines `answered` vs `needs_review`. On invalid/ambiguous outputs, reject and record only a coarse response-format classification, never source text or private prompts. Original failed tasks are never resumed automatically.

## Host acceptance and activation

A guarded release controller validates exact Git and source hashes, protected owner files, pre-install Ruff for the proposed patch and new modules, focused tests (including a fake-model-to-real-Bubblewrap repair cycle), full pytest, dashboard TypeScript and 9C5 isolated real worker acceptance. It commits only `mio/work_engineering.py`, `mio/scorpio9d1_response.py`, `tests/test_scorpio9d1_response.py`, this document. Non-force push only, then verified idle worker-only restart after a native-private SQLite backup. No production Work tasks are created or approved by release.

After deployment the owner must submit a **new** explicitly approved Engineering task—not a bounded Research follow-up—using the existing SCORPIO9D1 TEXTUTILS prompt. Inspect its run events for `model.format_recovered` or `validation.reject`, and the saved `verification.json` for exact 13-test evidence. A non-JSON model response is not proof of valid Python; a model still generating invalid/unusable output must be investigated separately. The owner can keep the previous failed run and its follow-ups as audit evidence. Never silently delete these records.
