"use client";

import { useCallback, useEffect, useState } from "react";
import styles from "./room.module.css";

type Project = { id: string; title: string };
type RunSummary = { id: string; prompt: string; state: string; mode: string; model: string | null };
type Detail = Project & { runs: RunSummary[] };
type Event = { phase: string; detail: string; created: number };
type Run = RunSummary & { events: Event[]; sources: { ref: string; url: string }[]; result: string | null; error: string | null };
type Overview = { projects: Project[]; permissions: Record<string, boolean> };
type Role = "supervisor" | "research" | "writer" | "review" | "delivery";
type AgentState = "idle" | "working" | "done" | "blocked";
const TERMINAL = new Set(["answered", "needs_review", "failed", "interrupted"]);

async function api<T>(path: string): Promise<T> {
  const response = await fetch(`/api/proxy/${path}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Local API unavailable (${response.status})`);
  return response.json() as Promise<T>;
}

function phaseSeen(events: Event[], ...phases: string[]) {
  return events.some((e) => phases.some((p) => e.phase === p || e.phase.startsWith(p + ".")));
}

function roleStatus(role: Role, run: Run | null): AgentState {
  if (!run) return "idle";
  const events = run.events;
  const ended = TERMINAL.has(run.state);
  const bad = run.state === "failed" || run.state === "interrupted";
  if (role === "supervisor") return bad || run.state === "needs_review" || phaseSeen(events, "model.review_unavailable") ? "blocked" : ended ? "done" : "working";
  if (role === "research") return phaseSeen(events, "web.error") ? "blocked" : phaseSeen(events, "web.evidence", "web.scholarly") ? "done" : phaseSeen(events, "web.search") && !ended ? "working" : "idle";
  if (role === "writer") return phaseSeen(events, "model.draft") ? (!ended && !phaseSeen(events, "model.review") ? "working" : "done") : "idle";
  if (role === "review") return phaseSeen(events, "model.review_unavailable") ? "blocked" : phaseSeen(events, "model.review", "model.refine") ? (ended || phaseSeen(events, "delivered") ? "done" : "working") : "idle";
  return phaseSeen(events, "delivered") ? "done" : bad ? "blocked" : "idle";
}

const team: { role: Role; name: string; desk: string; icon: string; description: string }[] = [
  { role: "research", name: "Research Desk", desk: "RESEARCH", icon: "⌕", description: "Evidence retrieval" },
  { role: "writer", name: "Creation Desk", desk: "DRAFTING", icon: "✎", description: "Local model drafting" },
  { role: "review", name: "Review Desk", desk: "QUALITY", icon: "✓", description: "Independent review attempt" },
  { role: "delivery", name: "Delivery Desk", desk: "RESULTS", icon: "▤", description: "Saved work products" },
];

function shortId(id: string) { return id.slice(0, 8); }
function stateText(state: AgentState): string {
  return { idle: "Standby", working: "Working", done: "Recorded", blocked: "Needs attention" }[state];
}

export default function ControlRoom() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState("");
  const [inspect, setInspect] = useState<Role>("supervisor");

  const loadProjects = useCallback(async () => {
    const info = await api<Overview>("work/overview");
    setOverview(info);
    setProjectId((value) => value ?? info.projects[0]?.id ?? null);
  }, []);

  useEffect(() => {
    const qs = new URLSearchParams(window.location.search);
    const initial = qs.get("project");
    if (initial && /^[0-9a-f]{32}$/.test(initial)) setProjectId(initial);
    void loadProjects().catch((e: Error) => setError(e.message));
  }, [loadProjects]);

  useEffect(() => {
    if (!projectId) { setDetail(null); setRunId(null); return; }
    let active = true;
    const poll = async () => {
      try {
        const info = await api<Detail>(`work/projects/${projectId}`);
        if (active) { setDetail(info); setRunId((old) => old && info.runs.some((item) => item.id === old) ? old : info.runs[0]?.id ?? null); }
      } catch (e) { if (active) setError(e instanceof Error ? e.message : "Cannot open project"); }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 4000);
    return () => { active = false; window.clearInterval(timer); };
  }, [projectId]);

  useEffect(() => {
    if (!runId) { setRun(null); return; }
    let active = true;
    const poll = async () => {
      try { const info = await api<Run>(`work/runs/${runId}`); if (active) setRun(info); }
      catch (e) { if (active) setError(e instanceof Error ? e.message : "Cannot load run"); }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 2300);
    return () => { active = false; window.clearInterval(timer); };
  }, [runId]);

  const active = !!run && !TERMINAL.has(run.state);
  const events = run?.events ?? [];
  const totalDone = team.filter((member) => roleStatus(member.role, run) === "done").length;
  const totalBlocked = team.filter((member) => roleStatus(member.role, run) === "blocked").length;
  const selectedRole = inspect === "supervisor" ? { name: "MioAgent Supervisor", description: "Coordinates the bounded Work task and records its outcome" } : team.find((member) => member.role === inspect)!;
  const related = inspect === "supervisor" ? events : inspect === "research" ? events.filter((e) => e.phase.startsWith("web.")) : inspect === "writer" ? events.filter((e) => e.phase === "model.draft" || e.phase === "model.refine") : inspect === "review" ? events.filter((e) => e.phase.startsWith("model.review")) : events.filter((e) => ["delivered", "error"].includes(e.phase));

  return <main className={styles.page}>
    <header className={styles.topbar}><a className={styles.brand} href="/chat"><span>✳</span> MioAgent <small>/ CONTROL ROOM</small></a><nav><a href="/chat">← Chat</a><a href="/work-mode">Work</a><a href="/projects-space">Projects</a></nav><span className={styles.operational}><i /> WORK EVENTS · LIVE</span></header>
    <div className={styles.layout}>
      <section className={styles.center}>
        <div className={styles.headline}><div><span className={styles.overline}>THE MIOAGENT OFFICE</span><h1>Your AI team, in motion<span>.</span></h1><p>Follow real tool and model activity as it happens. Each desk reflects saved evidence—not simulated work.</p></div><div className={styles.selectors}><label>PROJECT<select aria-label="Select project" value={projectId ?? ""} onChange={(e) => { setProjectId(e.target.value || null); setRunId(null); setRun(null); }}><option value="">Choose a project</option>{overview?.projects.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label><label>RUN<select aria-label="Select task" value={runId ?? ""} onChange={(e) => { setRunId(e.target.value || null); setRun(null); }}><option value="">No run</option>{detail?.runs.map((item) => <option key={item.id} value={item.id}>{`${item.prompt.slice(0, 45)} (${item.state})`}</option>)}</select></label></div></div>
        {error && <div className={styles.error} role="alert">{error}<button onClick={() => setError("")}>Dismiss</button></div>}
        <div className={styles.metrics}><div><span>SUPERVISOR</span><strong>{stateText(roleStatus("supervisor", run))}</strong></div><div><span>DESKS WITH RECORDED OUTPUT</span><strong>{totalDone} <small>/ 4</small></strong></div><div><span>NEEDS ATTENTION</span><strong>{totalBlocked}</strong></div><div><span>RUN STATUS</span><strong>{run?.state.replaceAll("_", " ") ?? "No run selected"}</strong></div></div>
        <section className={styles.office} aria-label="Visual office of evidence-backed MioAgent worker roles">
          <div className={styles.officeTop}><span>◎ LIVE PROJECT FLOOR</span><span>{run ? `RUN ${shortId(run.id)}` : "NO TASK SELECTED"}</span></div>
          <div className={styles.officeFloor}>
            <div className={styles.roomWall}><span>MIOAGENT · OPERATIONS FLOOR</span><div className={styles.wallWindows}><i /><i /><i /></div></div>
            <div className={`${styles.supervisor} ${styles[roleStatus("supervisor", run)]} ${inspect === "supervisor" ? styles.chosen : ""}`} role="button" tabIndex={0} aria-label="Inspect supervisor" onClick={() => setInspect("supervisor")} onKeyDown={(e) => { if (e.key === "Enter") setInspect("supervisor"); }}>
              <span className={styles.supervisorLabel}>SUPERVISOR DESK</span><div className={styles.person}>✳</div><div className={styles.deskSurface}><div className={styles.monitor}><span>MI</span></div><div className={styles.deskLeg} /></div><div className={styles.deskName}>MioAgent Supervisor</div><div className={styles.workerStatus}><i />{stateText(roleStatus("supervisor", run))}</div>
            </div>
            <div className={styles.teamGrid}>{team.map((person) => { const state = roleStatus(person.role, run); return <button type="button" className={`${styles.desk} ${styles[state]} ${inspect === person.role ? styles.chosen : ""}`} key={person.role} onClick={() => setInspect(person.role)} aria-label={`Inspect ${person.name}`}><small className={styles.deskLabel}>{person.desk}</small><div className={styles.deskDrawing}><div className={styles.avatar}>{person.icon}</div><div className={styles.table}><div className={styles.screen}><i /><i /><i /></div><div className={styles.keyboard}/></div></div><strong>{person.name}</strong><span className={styles.workerStatus}><i />{stateText(state)}</span></button>; })}</div>
            <div className={styles.floorNote}>{active ? "Active Work run · steps recorded as they occur" : "Standing by · no unverified work animation"}</div>
          </div>
          <div className={styles.officeFooter}><span>● Actual Work database events</span><span>Read-only view · No unapproved computer access</span></div>
        </section>
        <div className={styles.lower}><div className={styles.brief}><span className={styles.overline}>CURRENT ASSIGNMENT</span><h2>{run ? run.prompt : "No assignment selected"}</h2><p>{run?.result ? run.result.slice(0, 700) + (run.result.length > 700 ? "…" : "") : run?.error ?? "Choose a saved run to inspect its model, evidence, activity and outcome."}</p>{run && <a href={`/work-mode?project=${projectId}`}>Open full answer and sources ↗</a>}</div><div className={styles.truth}><span className={styles.overline}>HOW THIS ROOM WORKS</span><p>Research, creation, review and delivery desks light up only when the Work event log records a relevant action. A failed reviewer is shown as needing attention—not as a successful agent.</p><p>This release visualizes the current bounded workflow. Real autonomous delegation, retries, approvals and engineering tools are separate upcoming backend milestones.</p></div></div>
      </section>
      <aside className={styles.side}><div className={styles.sideHead}><span className={styles.overline}>AGENT INSPECTOR</span><h2>{selectedRole.name}</h2><p>{selectedRole.description}</p></div><div className={styles.sideState}><span>STATUS</span><b className={styles[roleStatus(inspect, run)]}>{stateText(roleStatus(inspect, run))}</b></div><div className={styles.sideState}><span>ACTIVE MODEL</span><b>{run?.model || "None recorded"}</b></div><div className={styles.sideState}><span>RUN MODE</span><b>{run?.mode ?? "—"}</b></div><h3>Verified activity <small>{related.length} steps</small></h3><div className={styles.timeline}>{related.map((item, index) => <div className={styles.event} key={`${item.phase}-${index}`}><span className={styles.eventMarker}/><div><strong>{item.phase}</strong><p>{item.detail}</p></div></div>)}{!related.length && <p className={styles.noEvents}>No recorded activity for this role. It is not currently executing a task.</p>}</div><div className={styles.sideFoot}><a href={`/work-mode${projectId ? `?project=${projectId}` : ""}`}>↗ View full task in Workspace</a><small>Role visualization is based on real phase events, not independent autonomous model workers.</small></div></aside>
    </div>
  </main>;
}
