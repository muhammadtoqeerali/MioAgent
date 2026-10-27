"use client";

import { useEffect, useState } from "react";
import { mioApi, postJson } from "./api";
import styles from "./scorpio.module.css";

type ReviewRun = {
  id: string; state: string; mode: string; prompt: string;
  result?: string | null; error?: string | null;
  events?: { phase: string; detail: string }[];
};

// Keep the exported allowlist for any existing read-only inspection consumers.
const SAFE_PATH = /^(mio|tests|scripts|docs)\/(?:[A-Za-z0-9_-]+\/)*[A-Za-z0-9_.-]+\.(py|md|ts|tsx)$/;
const DENIED_PARTS = new Set([".git", ".mioagent-private", "node_modules", ".next", "secrets", "private", "credentials", "downloads", "backups", "__pycache__", "venv", ".venv"]);
export function allowedSources(raw: string): string[] | null {
  const paths = raw.split(/[\n,]+/).map(x => x.trim()).filter(Boolean);
  if (paths.length < 1 || paths.length > 8 || new Set(paths).size !== paths.length) return null;
  if (paths.some(path => path.length > 160 || !SAFE_PATH.test(path) || path.split("/").some(part => DENIED_PARTS.has(part) || part === ".."))) return null;
  return paths;
}

const ENGINEERING_PREFIX = "SCORPIO9D1 TEXTUTILS: ";

export default function ScorpioApprovalPanel({ projectId, run, onSubmitted }: {
  projectId: string; run: ReviewRun; onSubmitted?: (newId: string) => void;
}) {
  const [submitting, setSubmitting] = useState(false);
  const [rejected, setRejected] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => { setRejected(false); setMessage(""); }, [run.id]);
  const active = run.state === "queued" || run.state === "running";
  const needsDecision = ["failed", "needs_review", "interrupted"].includes(run.state);
  // A proposed retry must retain the exact original owner-approved profile.
  // Never route an engineering failure into research or claim it is a resumed run.
  const textutilsTask = run.prompt.startsWith(ENGINEERING_PREFIX) ||
    ["normalize_whitespace", "count_words", "is_palindrome", "slugify"]
      .every(name => run.prompt.includes(name));
  // For an old task without the prefix, propose the fixed trusted contract;
  // do not carry old research follow-ups or untrusted extra instructions over.
  const proposedPrompt = run.prompt.startsWith(ENGINEERING_PREFIX)
    ? run.prompt
    : `${ENGINEERING_PREFIX} Build the offline Python textutils.py library implementing normalize_whitespace, count_words, is_palindrome, and slugify using only the standard library and the platform's independent 13 tests.`;
  const engineeringRetry = ["failed", "needs_review"].includes(run.state)
    && run.mode === "engineering" && textutilsTask
    && proposedPrompt.length <= 6000 && /^[0-9a-f]{32}$/.test(run.id)
    && (run.events ?? []).some(event => event.phase === "validation.reject");

  async function approve() {
    if (!engineeringRetry || submitting || rejected || !/^[0-9a-f]{32}$/.test(projectId)) return;
    setSubmitting(true); setMessage("");
    try {
      const response = await mioApi<{ id: string; mode: string }>(`work/projects/${projectId}/runs`,
        postJson({ prompt: proposedPrompt, task_type: "engineering", approved: true }));
      if (!/^[0-9a-f]{32}$/.test(response.id) || response.id === run.id || response.mode !== "engineering_queued")
        throw new Error("The API did not confirm a new engineering run");
      setMessage(`New approved engineering run: ${response.id.slice(0, 12)}. The original was not resumed.`);
      onSubmitted?.(response.id);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Approval could not be submitted."); }
    finally { setSubmitting(false); }
  }

  if (run.mode.startsWith("browser_")) return null;
  if (active) return <section className={styles.approval}><strong>Scorpio is working</strong><p>No permission decision is needed while this task is running.</p></section>;
  if (!needsDecision) return null;

  return <section className={styles.approval} aria-label="Owner approval decision">
    <div className={styles.actionHeading}><div><small>OWNER APPROVAL</small>
      <h3>{engineeringRetry ? "Scorpio proposes one new coding attempt" : "No automatic retry proposed"}</h3></div>
      <span className={styles.statusText}>{run.state.replaceAll("_", " ")}</span></div>
    <p>{engineeringRetry
      ? "The previous code response could not be accepted. Scorpio will regenerate this four-function Python task using the pinned text-utilities acceptance suite. The previous run stays unchanged."
      : "This result needs review. Scorpio will not change task type, request additional tools or start a new run without a suitable bounded proposal."}</p>
    <p className={styles.actionHint}>Permissions: private coding artifact and network-isolated Python tests only. No host shell, arbitrary files, browser tools, source deployment or Git push.</p>
    {run.error && <p className={styles.actionError}>Recorded error: {run.error}</p>}
    {rejected ? <p role="status" className={styles.actionHint}>Rejected for this view. No new task was queued. This dismissal is not a server-side audit record.</p>
      : <div className={styles.actionRow}>
        {engineeringRetry && <button type="button" className={styles.actionPrimary} disabled={submitting} onClick={() => void approve()}>
          {submitting ? "Submitting…" : "Approve one new engineering run"}</button>}
        <button type="button" disabled={submitting} onClick={() => setRejected(true)}>Reject — do nothing</button>
        <a href={`/work-mode?project=${projectId}`}>View evidence ↗</a>
      </div>}
    {message && <p className={styles.actionMessage} role="status">{message}</p>}
  </section>;
}
