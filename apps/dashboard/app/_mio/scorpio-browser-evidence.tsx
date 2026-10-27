"use client";

import { useEffect, useState } from "react";
import { mioApi, postJson, type WorkRun } from "./api";

type BrowserProposal = {
  run: string;
  project: string;
  url: string;
  prompt: string;
  decision: "proposed" | "approved" | "rejected";
  state: string;
  mode: string;
  consumed: number;
};

const ID = /^[0-9a-f]{32}$/;
const boxStyle = { padding: 18, border: "1px solid #536783", borderRadius: 12, marginTop: 16 };
const fieldStyle = { boxSizing: "border-box" as const, width: "100%", padding: 10, marginTop: 5, marginBottom: 12, borderRadius: 7 };

/** Only a deliberate owner click can send a browser decision; displaying a proposal does not grant access. */
export default function ScorpioBrowserEvidence({ projectId, run }: { projectId: string; run: WorkRun | null }) {
  const [goal, setGoal] = useState("");
  const [url, setUrl] = useState("");
  const [proposal, setProposal] = useState<BrowserProposal | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    let active = true;
    setProposal(null);
    setMessage("");
    if (!run || !ID.test(run.id) || !run.mode.startsWith("browser_")) {
      setProposal(null);
      return () => { active = false; };
    }
    void mioApi<BrowserProposal>(`work/runs/${run.id}/browser-proposal`).then(data => {
      if (active && data.run === run.id && data.project === projectId) setProposal(data);
    }).catch(() => { if (active) setProposal(null); });
    return () => { active = false; };
  }, [projectId, run?.id, run?.mode, run?.state]);

  if (!ID.test(projectId)) return null;
  const pending = proposal?.decision === "proposed" && proposal.state === "needs_review"
    && proposal.project === projectId && proposal.run === run?.id;
  const executing = run?.state === "queued" || run?.state === "running";
  const urlValid = /^https:\/\/[A-Za-z0-9.-]+(?:\/|\?|#|$)/.test(url.trim()) && url.length <= 1500;
  const awaitingProposalRead = run?.mode === "browser_proposed" && run.state === "needs_review";
  const mayPropose = !busy && !executing && !pending && !awaitingProposalRead && goal.trim().length >= 4 && goal.length <= 6000 && urlValid;

  async function createProposal() {
    if (!mayPropose) return;
    setBusy(true); setMessage("");
    try {
      const created = await mioApi<BrowserProposal>(`work/projects/${projectId}/browser-proposals`,
        postJson({ prompt: goal.trim(), url: url.trim() }));
      if (!ID.test(created.run) || created.project !== projectId || created.decision !== "proposed")
        throw new Error("Server did not confirm an unapproved browser proposal");
      setProposal(created);
      setGoal(""); setUrl("");
      setMessage("Proposal saved. No website has been fetched. Approve or Reject below.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Browser proposal unavailable");
    } finally { setBusy(false); }
  }

  async function decide(approve: boolean) {
    if (!pending || !proposal || proposal.project !== projectId || proposal.run !== run?.id || !ID.test(proposal.run) || busy) return;
    setBusy(true); setMessage("");
    try {
      const changed = await mioApi<BrowserProposal>(`work/runs/${proposal.run}/browser-decision`,
        postJson({ approve }));
      if (changed.run !== proposal.run || changed.project !== projectId ||
        changed.decision !== (approve ? "approved" : "rejected"))
        throw new Error("Owner decision was not confirmed by Work API");
      setProposal(changed);
      setMessage(approve
        ? "One-use browser access approved and queued. Work status updates automatically."
        : "Browser request rejected and recorded; no access granted.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not record browser decision");
    } finally { setBusy(false); }
  }

  return <section style={boxStyle} aria-label="Owner-approved public browser evidence">
    <h3>Read one public webpage</h3>
    <p>Request a single HTTPS document through Scorpio's verified research browser. It cannot download, install, access private networks, or run website JavaScript. Only an explicit approval can queue the request.</p>
    {pending && proposal ? <div>
      <p><strong>Permission requested:</strong> one public HTTPS document</p>
      <p><strong>Task:</strong> {proposal.prompt}</p>
      <p><strong>Exact URL:</strong> <code>{proposal.url}</code></p>
      <p>No access has occurred. An approval is valid only for this Work run and expires within three minutes.</p>
      <button type="button" disabled={busy} onClick={() => void decide(true)}>Approve once</button>{" "}
      <button type="button" disabled={busy} onClick={() => void decide(false)}>Reject</button>
    </div> : <>
      {proposal && <p role="status"><strong>Last browser decision:</strong> {proposal.decision}. Run state: {run?.state ?? proposal.state}. {proposal.consumed ? "Grant consumed." : "No execution claimed."}</p>}
      <label htmlFor="scorpio-browser-goal">Task goal</label>
      <textarea id="scorpio-browser-goal" style={fieldStyle} rows={2} maxLength={6000}
        value={goal} onChange={event => setGoal(event.target.value)} disabled={busy || executing}
        placeholder="Read this official webpage and record verified source evidence"/>
      <label htmlFor="scorpio-browser-url">Exact public HTTPS URL</label>
      <input id="scorpio-browser-url" style={fieldStyle} type="url" maxLength={1500}
        value={url} onChange={event => setUrl(event.target.value)} disabled={busy || executing}
        placeholder="https://www.python.org/" />
      <button type="button" disabled={!mayPropose} onClick={() => void createProposal()}>
        {busy ? "Submitting…" : "Request browser approval"}
      </button>
      {executing && <p>Another Work action is active. Wait for it to finish before proposing browser access.</p>}
    </>}
    {message && <p role="status">{message}</p>}
    <p><small>Evidence verification only: the result proves retrieval and isolated rendering, not the truth of every statement on the page. No automatic answer generation or general browsing is enabled.</small></p>
  </section>;
}
