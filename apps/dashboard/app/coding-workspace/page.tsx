"use client";
import { useCallback, useEffect, useState } from "react";
import { mioApi, postJson } from "../_mio/api";
import s from "./coding-workspace.module.css";

type Case = { id: string; title: string };
type Evidence = {
  kind: string; audit_sha256: string; audit_events: number;
  original_unchanged: boolean; applied_to_owner_repository: boolean;
  attempts: { attempt: number; passed: boolean; tests_run: number; selected_tests_run: boolean;
    feedback: string; proposed_sha256: string }[];
};
type Job = { id: string; case_name: string; state: string; created: number;
  events: { phase: string; detail: string; created: number }[]; result: Evidence | null; error: string | null };
type Summary = { id: string; case_name: string; state: string; created: number };
type Status = { release: string; mode: string; llm_autonomy: boolean;
  model_inference_enabled: boolean; owner_repo_apply_enabled: boolean;
  case_options: Case[]; note: string };

export default function CodingWorkspace() {
  const [status, setStatus] = useState<Status | null>(null);
  const [jobs, setJobs] = useState<Summary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [caseName, setCaseName] = useState("arithmetic");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const refresh = useCallback(async () => {
    const [state, items] = await Promise.all([
      mioApi<Status>("scorpio/coding/status"),
      mioApi<{ jobs: Summary[] }>("scorpio/coding/jobs"),
    ]);
    setStatus(state); setJobs(items.jobs);
    setSelected(old => old && items.jobs.some(j => j.id === old) ? old : items.jobs[0]?.id ?? null);
  }, []);
  useEffect(() => {
    void refresh().catch(e => setError(e instanceof Error ? e.message : "Backend unavailable"));
    const timer = window.setInterval(() => void refresh().catch(() => {}), 7000);
    return () => window.clearInterval(timer);
  }, [refresh]);
  useEffect(() => {
    if (!selected) { setJob(null); return; }
    let active = true;
    const tick = async () => {
      try {
        const detail = await mioApi<Job>(`scorpio/coding/jobs/${selected}`);
        if (active) setJob(detail);
      } catch (e) { if (active) setError(e instanceof Error ? e.message : "Job unavailable"); }
    };
    void tick(); const timer = window.setInterval(() => void tick(), 1500);
    return () => { active = false; window.clearInterval(timer); };
  }, [selected]);
  async function create() {
    if (busy) return;
    setBusy(true); setError("");
    try {
      const fresh = await mioApi<Job>("scorpio/coding/jobs", postJson({case_name:caseName, approved:true}));
      setSelected(fresh.id); setJob(fresh); await refresh();
    } catch(e) { setError(e instanceof Error ? e.message : "Creation failed"); }
    finally { setBusy(false); }
  }
  async function action(kind: "execute" | "cancel") {
    if (!selected || busy) return;
    if (kind === "execute" && !window.confirm("Run a deterministic synthetic two-attempt sandbox rehearsal? No model inference or owner repository changes.")) return;
    setBusy(true); setError("");
    try {
      const next = await mioApi<Job>(`scorpio/coding/jobs/${selected}/${kind}`, postJson({approved:true}));
      setJob(next); await refresh();
    } catch(e) { setError(e instanceof Error ? e.message : "Action failed"); }
    finally { setBusy(false); }
  }
  return <div className={s.page}>
    <header className={s.header}>
      <div><div className={s.eyebrow}>SCORPIO S12C · CONTROLLED ENGINEERING</div>
        <h2>Coding workspace</h2>
        <p>Persistent evidence, bounded sandbox tests, and reviewable offline rehearsals.</p>
      </div><div className={s.status}>{status?.mode === "offline_rehearsal_only" ? "Offline rehearsal only" : "Backend status unavailable"}</div>
    </header>
    <div className={s.notice}><strong>Real autonomous coding is not enabled.</strong> The platform uses fixed reference edits for these demonstrations. It does not call Ollama, execute a model-generated plan, or write to your repository. A passing rehearsal is not evidence of LLM autonomy.</div>
    {error && <div className={s.error} role="alert">{error}</div>}
    <div className={s.metrics}>
      <article><span>Model-driven action</span><b>{status?.model_inference_enabled ? "Enabled" : "Disabled"}</b></article>
      <article><span>Original repo writes</span><b>{status?.owner_repo_apply_enabled ? "Enabled" : "Blocked"}</b></article>
      <article><span>Saved rehearsals</span><b>{jobs.length}</b></article>
    </div>
    <div className={s.columns}>
      <aside className={s.panel}>
        <h3>New sandbox rehearsal</h3>
        <label className={s.label} htmlFor="scorpio-case">Fixed test fixture</label>
        <select id="scorpio-case" className={s.select} value={caseName} onChange={e=>setCaseName(e.target.value)}>
          {(status?.case_options ?? []).map(c=><option key={c.id} value={c.id}>{c.title}</option>)}
        </select>
        <button className={s.primary} onClick={()=>void create()} disabled={busy || !status}>Create offline job</button>
        <p className={s.help}>Creating a job does not execute code. A second explicit approval is needed for the sandbox run.</p>
        <h3 className={s.section}>Saved jobs</h3>
        {jobs.length === 0 && <p className={s.help}>No saved rehearsals yet.</p>}
        {jobs.map(j=><button key={j.id} className={`${s.job} ${selected===j.id?s.active:""}`} onClick={()=>setSelected(j.id)}>
          <strong>{status?.case_options.find(c=>c.id===j.case_name)?.title ?? j.case_name}</strong>
          <small>{j.state.replaceAll("_"," ")} · {j.id.slice(0,8)}</small>
        </button>)}
      </aside>
      <section className={s.panel}>
        <h3>Execution evidence</h3>
        {!job ? <p className={s.help}>Choose a saved rehearsal to inspect verified events.</p> : <>
          <div className={s.summary}><div><strong>{job.case_name}</strong><small>Job {job.id}</small></div><span>{job.state.replaceAll("_"," ")}</span></div>
          <div className={s.actions}>
            <button className={s.primary} disabled={busy || job.state!=="draft"} onClick={()=>void action("execute")}>{busy?"Working…":"Approve & run fixed sandbox demo"}</button>
            <button className={s.secondary} disabled={busy || !["draft","running"].includes(job.state)} onClick={()=>void action("cancel")}>Cancel</button>
          </div>
          {job.result && <section className={s.result}>
            <h4>{job.state==="verified_rehearsal"?"Reference replay passed":"Reference replay outcome"}</h4>
            <p>Original files unchanged: <strong>{String(job.result.original_unchanged)}</strong></p>
            <p>Owner repository modified: <strong>{String(job.result.applied_to_owner_repository)}</strong></p>
            {job.result.attempts.map(a=><div key={a.attempt} className={s.attempt}>
              <strong>Attempt {a.attempt}: {a.passed?"PASS":"FAIL"}</strong> · {a.tests_run} sandbox tests
              <details><summary>Verifier feedback</summary><pre>{a.feedback}</pre></details>
            </div>)}
            <p className={s.hash}>Audit SHA-256: {job.result.audit_sha256}</p>
          </section>}
          {job.error && <p className={s.error}>Execution failure: {job.error}</p>}
          <h4>Persistent event timeline</h4>
          <div className={s.timeline}>{job.events.map((e,i)=><div key={`${e.phase}-${i}`}>
            <strong>{e.phase.replaceAll("_"," ")}</strong><p>{e.detail}</p>
            <small>{new Date(e.created*1000).toLocaleString()}</small>
          </div>)}</div>
        </>}
      </section>
    </div>
    <footer className={s.footer}>Source-only approvals remain separate from GitHub publication. Ollama, KIOS, host shell, and arbitrary workstation directories are out of scope.</footer>
  </div>;
}
