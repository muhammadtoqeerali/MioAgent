"use client";

import { useState } from "react";
import { mioApi, postJson } from "./api";
import styles from "./scorpio.module.css";

type ReviewRun = {
  id: string; state: string; mode: string; prompt: string;
  result?: string | null; error?: string | null;
  events?: { phase: string; detail: string }[];
};

const SAFE_PATH = /^(mio|tests|scripts|docs)\/(?:[A-Za-z0-9_-]+\/)*[A-Za-z0-9_.-]+\.(py|md|ts|tsx)$/;
const DENIED_PARTS = new Set([".git", ".mioagent-private", "node_modules", ".next", "secrets", "private", "credentials", "downloads", "backups", "__pycache__", "venv", ".venv"]);

export function allowedSources(raw: string): string[] | null {
  const paths = raw.split(/[\n,]+/).map(x => x.trim()).filter(Boolean);
  if (paths.length < 1 || paths.length > 8 || new Set(paths).size !== paths.length) return null;
  if (paths.some(path => path.length > 160 || !SAFE_PATH.test(path) || path.split("/").some(part => DENIED_PARTS.has(part) || part === ".."))) return null;
  return paths;
}

export default function ScorpioApprovalPanel({ projectId, run, onSubmitted }: {
  projectId: string; run: ReviewRun; onSubmitted?: (newId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [choice, setChoice] = useState<"bounded" | "inspection">("bounded");
  const [feedback, setFeedback] = useState("");
  const [sources, setSources] = useState("mio/work_agent.py\nmio/work_core.py");
  const [approved, setApproved] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState("");
  const active = run.state === "queued" || run.state === "running";
  const review = ["needs_review", "failed", "interrupted"].includes(run.state);
  const inspection = choice === "inspection";
  const selectedSources = allowedSources(sources);
  const ready = !submitting && !active && approved && feedback.trim().length >= 10 && (!inspection || selectedSources !== null);
  const reason = run.state === "needs_review"
    ? "This run has finished but its output needs your review. Its previous execution cannot be silently resumed."
    : run.state === "interrupted"
      ? "The prior worker run was interrupted. You can submit a new bounded follow-up, not resume an unknown checkpoint."
      : run.state === "failed"
        ? "The prior task failed. Review its error and give new guidance before retrying."
        : active ? "The worker is still processing this run. Wait for a terminal state before starting another." : "The completed result is available for review.";

  async function submit() {
    if (!ready || !projectId || !/^[0-9a-f]{32}$/.test(projectId)) return;
    setSubmitting(true); setMessage("");
    try {
      const prompt = [
        `Owner-authorized NEW follow-up to Work run ${run.id}.`,
        `Prior request (context only): ${run.prompt.slice(0, 850)}`,
        `Owner's new instructions: ${feedback.trim()}`,
        "Use only already-supported bounded capabilities. Stop and report unsupported steps. Do not claim an interrupted run resumed, do not make implicit permission grants."
      ].join("\n\n").slice(0, 5800);
      const response = await mioApi<{ id: string; mode: string }>(`work/projects/${projectId}/runs`,
        postJson({ prompt, task_type: choice, approved: true, ...(inspection ? { sources: selectedSources } : {}) }));
      if (!/^[0-9a-f]{32}$/.test(response.id)) throw new Error("Invalid run identity returned by API");
      setOpen(false); setFeedback(""); setApproved(false);
      setMessage(`New ${choice} task queued: ${response.id.slice(0, 12)}. This is a new run, not an automatic resume.`);
      onSubmitted?.(response.id);
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : "The Work API did not accept the follow-up.");
    } finally { setSubmitting(false); }
  }

  return <section className={styles.approval} aria-label="Owner review and next action">
    <div className={styles.actionHeading}><div><small>OWNER ACTION CENTER</small><h3>{active ? "Work is in progress" : review ? "Your attention is needed" : "Run reviewed"}</h3></div><span className={styles.statusText}>{run.state.replaceAll("_", " ")}</span></div>
    <p>{reason}</p>
    {run.error && <p className={styles.actionError}>Last error: {run.error}</p>}
    {run.state === "needs_review" && <p className={styles.actionHint}>“Needs review” can mean deliberately unverified evidence, not necessarily a failure or an outstanding tool-permission request. Inspect the events and outcome before deciding.</p>}
    {!active && <div className={styles.actionRow}>
      <button type="button" className={styles.actionPrimary} onClick={() => setOpen(!open)}>{open ? "Close next-step form" : "Give feedback / approve next step"}</button>
      <a href={`/work-mode?project=${projectId}`}>Full task evidence ↗</a>
    </div>}
    {open && !active && <div className={styles.actionForm}>
      <div className={styles.choiceGrid} role="group" aria-label="New run type">
        <label><input type="radio" checked={!inspection} onChange={() => setChoice("bounded")}/> Bounded research or writing</label>
        <label><input type="radio" checked={inspection} onChange={() => setChoice("inspection")}/> Read-only source inspection</label>
      </div>
      <label>What should Scorpio do next?
        <textarea value={feedback} maxLength={2200} onChange={e => setFeedback(e.target.value)} placeholder="Describe what was missing, what to change, or the exact question to investigate next (at least 10 characters)." />
      </label>
      {inspection && <label>Explicit tracked source allowlist (1–8 files; one per line)
        <textarea value={sources} maxLength={1280} onChange={e => setSources(e.target.value)} spellCheck={false}/>
        {!selectedSources && <span className={styles.actionError}>Select 1–8 unique paths under mio/, tests/, scripts/ or docs/, using supported source extensions.</span>}
      </label>}
      <label className={styles.confirm}><input type="checkbox" checked={approved} onChange={e => setApproved(e.target.checked)}/> I approve this specific new {inspection ? "read-only inspection" : "bounded follow-up"} task. It does not grant terminal, filesystem-write or browser permissions.</label>
      <div className={styles.actionRow}><button type="button" className={styles.actionPrimary} disabled={!ready} onClick={() => void submit()}>{submitting ? "Submitting…" : "Approve and start NEW run"}</button><button type="button" onClick={() => { setOpen(false); setApproved(false); }}>Not now</button></div>
      <p className={styles.actionHint}>Only the authenticated Work API can queue a task. The worker enforces one active run at a time and the existing inspection opt-in; this panel grants no new tools.</p>
    </div>}
    {message && <p className={styles.actionMessage} role="status">{message}</p>}
  </section>;
}
