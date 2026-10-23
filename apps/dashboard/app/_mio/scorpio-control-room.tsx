"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import ScorpioApprovalPanel from "./scorpio-approval-panel";
import RichText from "./rich-text";
import styles from "./scorpio.module.css";
import { mioApi, type WorkProject, type WorkProjectDetail, type WorkRun } from "./api";

type Overview = { projects: WorkProject[]; permissions: Record<string, boolean>; release?: string };
const TERMINAL = new Set(["answered", "failed", "interrupted", "needs_review"]);
const label = (text: string) => text.replaceAll("_", " ");
const short = (text: string) => text.slice(0, 8);

function statusKind(run: WorkRun | null) {
  if (!run) return "idle";
  if (["queued", "running"].includes(run.state)) return "active";
  if (run.state === "needs_review") return "attention";
  if (run.state === "failed" || run.state === "interrupted") return "error";
  return "done";
}

export default function ScorpioControlRoom() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [projectId, setProjectId] = useState("");
  const [runId, setRunId] = useState("");
  const [detail, setDetail] = useState<WorkProjectDetail | null>(null);
  const [run, setRun] = useState<WorkRun | null>(null);
  const [error, setError] = useState("");
  const [connected, setConnected] = useState(false);
  const [lastSync, setLastSync] = useState<Date | null>(null);
  const [tab, setTab] = useState<"activity" | "outcome" | "controls">("activity");
  const [filter, setFilter] = useState<"all" | "attention" | "active">("all");

  const loadOverview = useCallback(async () => {
    try {
      const next = await mioApi<Overview>("work/overview");
      setOverview(next);
      const queryProject = new URLSearchParams(window.location.search).get("project");
      setProjectId((current) => current && next.projects.some(p => p.id === current) ? current
        : queryProject && next.projects.some(p => p.id === queryProject) ? queryProject
          : next.projects[0]?.id ?? "");
      setError(""); setConnected(true); setLastSync(new Date());
    } catch (cause) { setConnected(false); setError(cause instanceof Error ? cause.message : "Work API is unavailable"); }
  }, []);

  useEffect(() => {
    void loadOverview();
    const timer = window.setInterval(() => void loadOverview(), 15000);
    return () => window.clearInterval(timer);
  }, [loadOverview]);

  useEffect(() => {
    if (!projectId) { setDetail(null); setRunId(""); return; }
    let mounted = true;
    const tick = async () => {
      try {
        const info = await mioApi<WorkProjectDetail>(`work/projects/${projectId}`);
        if (mounted) {
          setDetail(info);
          setRunId(current => {
            if (current && info.runs.some(x => x.id === current)) return current;
            const queryRun = new URLSearchParams(window.location.search).get("run");
            return queryRun && info.runs.some(x => x.id === queryRun) ? queryRun : info.runs[0]?.id ?? "";
          });
        }
      } catch (cause) { if (mounted) setError(cause instanceof Error ? cause.message : "Project unavailable"); }
    };
    void tick();
    const timer = window.setInterval(() => void tick(), 3500);
    return () => { mounted = false; window.clearInterval(timer); };
  }, [projectId]);

  useEffect(() => {
    if (!runId) { setRun(null); return; }
    let mounted = true;
    const tick = async () => {
      try {
        const current = await mioApi<WorkRun>(`work/runs/${runId}`);
        if (mounted) { setRun(current); setLastSync(new Date()); }
      } catch (cause) { if (mounted) setError(cause instanceof Error ? cause.message : "Run evidence unavailable"); }
    };
    void tick();
    const timer = window.setInterval(() => void tick(), 2200);
    return () => { mounted = false; window.clearInterval(timer); };
  }, [runId]);

  const tasks = detail?.runs ?? [];
  const stats = useMemo(() => ({
    total: tasks.length,
    active: tasks.filter(t => t.state === "running" || t.state === "queued").length,
    attention: tasks.filter(t => ["needs_review", "failed", "interrupted"].includes(t.state)).length,
    answered: tasks.filter(t => t.state === "answered").length,
  }), [tasks]);
  const shownTasks = tasks.filter(t => filter === "all" || (filter === "active" && ["running", "queued"].includes(t.state)) || (filter === "attention" && ["needs_review", "failed", "interrupted"].includes(t.state)));
  const state = statusKind(run);
  const sourceEntries = Array.isArray(run?.sources) ? run.sources : [];

  return <div className={styles.room}>
    <aside className={styles.side}>
      <a href="/control-room" className={styles.brand} aria-label="Scorpio Control Room home"><img src="/scorpio-mark.svg" alt="Scorpio scorpion mark" width="51" height="51"/><span>Scorpio<small>AI CONTROL ROOM</small></span></a>
      <div className={styles.sideLabel}>OPERATIONS</div>
      <a className={styles.activeNav} href="/control-room">◈ <span>Control Room</span></a>
      <a className={styles.nav} href="/work-mode">▣ <span>Work &amp; Tasks</span></a>
      <a className={styles.nav} href="/work">◇ <span>Projects &amp; Files</span></a>
      <a className={styles.nav} href="/work/reviews">◉ <span>Engineering Reviews</span></a>
      <div className={styles.sideLabel}>WORKSPACE</div>
      <a className={styles.nav} href="/chat">✧ <span>Chat</span></a>
      <a className={styles.nav} href="/studio">▦ <span>Studio</span></a>
      <a className={styles.nav} href="/intelligence">⌘ <span>Intelligence</span></a>
      <div className={styles.sideFoot}><strong>Owner-controlled</strong><span>No unrestricted host access</span><span>Actual Work database records only</span></div>
    </aside>
    <main className={styles.main}>
      <header className={styles.top}><div><div className={styles.eyebrow}>OPERATIONS / CONTROL ROOM</div><h1>Scorpio Control Room</h1><p>Follow real tasks, review evidence, and choose the next approved step.</p></div><div className={styles.topActions}><span className={styles.live}>{connected ? "● Work API connected" : "◯ Work API unavailable"}</span><a href="/work-mode">＋ New Work assignment</a></div></header>
      {error && <div className={styles.alert} role="alert"><strong>Service notice</strong> {error}<button onClick={() => setError("")}>Dismiss</button></div>}
      <div className={styles.content}>
        <div className={styles.filters}><div><label htmlFor="scorpio-project">Selected project</label><select id="scorpio-project" value={projectId} onChange={e => {setProjectId(e.target.value);setRunId("");setRun(null);}}><option value="">Select a project</option>{overview?.projects.map(p => <option value={p.id} key={p.id}>{p.title}</option>)}</select></div><span className={styles.sync}>{lastSync ? `Last refreshed ${lastSync.toLocaleTimeString()}` : "Connecting…"} · Auto-refresh</span></div>
        <section className={styles.metrics} aria-label="Selected project Work metrics">
          <div><span>PROJECT TASKS</span><strong>{stats.total}</strong><small>Up to 50 recent runs</small></div>
          <div><span>QUEUED / RUNNING</span><strong>{stats.active}</strong><small>Independent Work worker</small></div>
          <div><span>NEEDS REVIEW OR HELP</span><strong>{stats.attention}</strong><small>Owner action available</small></div>
          <div><span>ANSWERED</span><strong>{stats.answered}</strong><small>Delivered results</small></div>
        </section>
        <div className={styles.columns}>
          <section className={styles.listPanel} aria-label="Work queue"><div className={styles.panelHead}><div><small>LIVE PROJECT</small><h2>Work queue</h2></div><a href="/work-mode">Manage work ↗</a></div>
            <div className={styles.tabs}><button className={filter==="all"?styles.activeTab:""} onClick={()=>setFilter("all")}>All ({stats.total})</button><button className={filter==="attention"?styles.activeTab:""} onClick={()=>setFilter("attention")}>Needs input ({stats.attention})</button><button className={filter==="active"?styles.activeTab:""} onClick={()=>setFilter("active")}>Active ({stats.active})</button></div>
            <div className={styles.taskList}>{shownTasks.map(t=><button key={t.id} aria-pressed={runId===t.id} className={`${styles.task} ${runId===t.id?styles.selectedTask:""}`} onClick={()=>{setRunId(t.id);setTab("activity");}}><span className={styles.taskIcon}>{t.mode==="inspection"||t.mode==="inspection_queued"?"⌕":t.mode.includes("engineering")?"{ }":"✧"}</span><span className={styles.taskText}><strong>{t.prompt.slice(0,94)}{t.prompt.length>94?"…":""}</strong><small>Run {short(t.id)} · {label(t.mode)}</small></span><span className={`${styles.status} ${styles[t.state==="needs_review"?"attention":t.state==="failed"||t.state==="interrupted"?"error":TERMINAL.has(t.state)?"done":"active"]}`}>{label(t.state)}</span></button>)}{!shownTasks.length&&<p className={styles.empty}>No tasks in this view. {projectId?"Start a Work assignment, or choose a different filter.":"Choose a project to see its actual queue."}</p>}</div>
          </section>
          <section className={styles.detailPanel} aria-label="Selected task and owner decisions"><div className={styles.panelHead}><div><small>TASK INSPECTOR</small><h2>{run ? `Run ${short(run.id)}` : "Choose a task"}</h2></div><span className={`${styles.status} ${styles[state]}`}>{run?label(run.state):"Idle"}</span></div>
            {run ? <><p className={styles.prompt}>{run.prompt}</p><div className={styles.runMeta}><span>Mode: <strong>{label(run.mode)}</strong></span><span>Model: <strong>{run.model ?? "None recorded"}</strong></span><span>Evidence events: <strong>{run.events.length}</strong></span></div>
              <div className={styles.tabs}><button className={tab==="activity"?styles.activeTab:""} onClick={()=>setTab("activity")}>Activity</button><button className={tab==="outcome"?styles.activeTab:""} onClick={()=>setTab("outcome")}>Outcome</button><button className={tab==="controls"?styles.activeTab:""} onClick={()=>setTab("controls")}>Access &amp; controls</button></div>
              {tab==="activity"&&<div className={styles.timeline}>{run.events.length ? run.events.map((e,i)=><div key={`${e.phase}-${i}`} className={styles.event}><b>{e.phase}</b><p>{e.detail}</p></div>):<p className={styles.empty}>No evidence events recorded yet.</p>}{["running","queued"].includes(run.state)&&<p className={styles.hint}>The queue is still active. Events update automatically.</p>}</div>}
              {tab==="outcome"&&<div className={styles.outcome}>{run.result?<RichText text={run.result}/>:<p className={styles.empty}>No result has been saved yet.</p>}{run.error&&<p className={styles.actionError}>Error: {run.error}</p>}{sourceEntries.length>0&&<div className={styles.sourceList}><h3>Recorded sources</h3>{sourceEntries.map((item,index)=>typeof item==="string"?<div key={index}>{item}</div>:<a key={index} href={item.url} target="_blank" rel="noopener noreferrer">{item.title||item.ref||"Source"} ↗</a>)}</div>}</div>}
              {tab==="controls"&&<div className={styles.controls}><h3>Backend-enforced capability report</h3>{Object.entries(overview?.permissions??{}).map(([key,value])=><div key={key}><span>{label(key)}</span><strong>{value?"Available (task-scoped)":"Unavailable"}</strong></div>)}<p className={styles.hint}>This is descriptive status from the authenticated backend, not a set of permission switches. General host shell, arbitrary folders and automatic browser operations are not granted here.</p></div>}
              <ScorpioApprovalPanel key={run.id} projectId={projectId} run={run} onSubmitted={id=>{setRunId(id);setTab("activity");void loadOverview();}}/>
            </> : <div className={styles.welcome}><img src="/scorpio-mark.svg" alt="" width="78" height="78"/><h3>Your Work supervisor</h3><p>Select a project and a saved task. Scorpio will display its real stages and offer bounded follow-up actions where supported.</p><a href="/work-mode">Start a new assignment ↗</a></div>}
          </section>
        </div>
        <div className={styles.bottom}><section><div className={styles.panelHead}><div><small>OPERATOR GUIDANCE</small><h2>What happens when an agent stops?</h2></div></div><p><b>Needs review</b> means a task has finished with evidence that requires your judgment. <b>Failed</b> or <b>Interrupted</b> means it could not complete. Open the task, inspect its events and result, provide feedback, and explicitly approve a new bounded follow-up. No silent or simulated resume occurs.</p></section><section><div className={styles.panelHead}><div><small>SECURITY BOUNDARY</small><h2>Permissions are real—not decorative</h2></div></div><p>Only supported Work operations are available from this screen. Read-only source inspection requires dual API/worker opt-in. Workstation shell, arbitrary file writes, Git publishing, and broader computer control need separately validated backend permissions and owner approval.</p></section></div>
      </div>
    </main>
  </div>;
}
