"use client";
import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import ScorpioApprovalPanel from "./scorpio-approval-panel";
import { mioApi, type WorkProject, type WorkRun } from "./api";

type WorkOverview={projects:WorkProject[];permissions:Record<string,boolean>;release:string};
type RunSummary={id:string;prompt:string;state:string;mode:string;model:string|null};
type ProjectDetail={id:string;title:string;runs:RunSummary[]};
type Entry={project:WorkProject;summary:RunSummary;detail?:WorkRun};
const actionable=new Set(["needs_review","failed","interrupted","answered"]);
const stateName=(s:string)=>s.replaceAll("_"," ");

export function useScorpioActivity(){
 const [overview,setOverview]=useState<WorkOverview|null>(null);
 const [entries,setEntries]=useState<Entry[]>([]);
 const [error,setError]=useState("");
 const [loading,setLoading]=useState(true);
 const [version,setVersion]=useState(0);
 useEffect(()=>{
   let live=true;
   const tick=async()=>{
    try{
     const info=await mioApi<WorkOverview>("work/overview");
     const projects=info.projects.slice(0,40);
     const details=await Promise.allSettled(projects.map(p=>mioApi<ProjectDetail>(`work/projects/${p.id}`)));
     const rows:Entry[]=[];
     details.forEach((answer,i)=>{if(answer.status==="fulfilled")answer.value.runs.forEach(summary=>rows.push({project:projects[i],summary}));});
     if(live){setOverview(info);setEntries(rows.slice(0,250));setError(details.some(x=>x.status==="rejected")?"Some projects could not be loaded":"");}
    }catch(e){if(live)setError(e instanceof Error?e.message:"Could not load Work data");}
    finally{if(live)setLoading(false);}
   };
   void tick();const timer=window.setInterval(()=>void tick(),6000);
   return()=>{live=false;window.clearInterval(timer);};
 },[version]);
 return {overview,entries,error,loading,refresh:()=>setVersion(n=>n+1)};
}

export function ScorpioPageHeading({title,description,action}:{title:string;description:string;action?:ReactNode}){
 return <div className="scorpio8a-pageHeading"><div><p className="scorpio8a-overline">SCORPIO / OPERATIONS</p><h2>{title}</h2><p>{description}</p></div>{action}</div>;
}

export function ScorpioApprovals(){
 const {entries,error,loading,refresh}=useScorpioActivity();
 const [selected,setSelected]=useState("");
 const [run,setRun]=useState<WorkRun|null>(null);
 const [detailError,setDetailError]=useState("");
 const needs=entries.filter(e=>["needs_review","failed","interrupted"].includes(e.summary.state));
 useEffect(()=>{if(!selected&&needs[0])setSelected(needs[0].summary.id);},[selected,needs]);
 useEffect(()=>{if(!selected){setRun(null);return;}let live=true;const update=async()=>{try{const value=await mioApi<WorkRun>(`work/runs/${selected}`);if(live){setRun(value);setDetailError("");}}catch(e){if(live)setDetailError(e instanceof Error?e.message:"Evidence unavailable");}};void update();const t=window.setInterval(()=>void update(),5000);return()=>{live=false;window.clearInterval(t);};},[selected]);
 const current=entries.find(e=>e.summary.id===selected);
 return <div className="scorpio8a-page"><ScorpioPageHeading title="Attention & approvals" description="Review saved Work evidence and explicitly authorize a new bounded follow-up. These are review cases, not outstanding host-tool permission grants." action={<button className="scorpio8a-button" onClick={refresh}>Refresh</button>}/>
 {error&&<p className="scorpio8a-error" role="alert">{error}</p>}
 <div className="scorpio8a-panelGrid"><section className="scorpio8a-card"><h3>Review queue <span>{needs.length}</span></h3>{loading&&<p>Loading saved tasks…</p>}{!needs.length&&!loading&&<p>No Work runs currently require review.</p>}{needs.map(e=><button key={e.summary.id} className={`scorpio8a-queueRow ${selected===e.summary.id?"selected":""}`} onClick={()=>{setSelected(e.summary.id);setRun(null);}}><span><strong>{e.summary.prompt.slice(0,90)}</strong><small>{e.project.title} · {e.summary.id.slice(0,8)}</small></span><em>{stateName(e.summary.state)}</em></button>)}</section>
 <section className="scorpio8a-card scorpio8a-review"><h3>{run?`Run ${run.id.slice(0,8)}`:"Select a Work run"}</h3>{detailError&&<p className="scorpio8a-error">{detailError}</p>}{run&&current&&<><p className="scorpio8a-context">{run.prompt}</p><p className="scorpio8a-meta">State: {stateName(run.state)} · Mode: {run.mode} · {run.events.length} audited events</p>{run.error&&<p className="scorpio8a-error">{run.error}</p>}{run.result&&<div className="scorpio8a-result">{run.result}</div>}<details><summary>Show recorded steps</summary>{run.events.map((e,i)=><p key={i}><strong>{e.phase}</strong> — {e.detail}</p>)}</details>{actionable.has(run.state)&&<ScorpioApprovalPanel projectId={current.project.id} run={run} onSubmitted={()=>{refresh();}}/>}<Link className="scorpio8a-inlineLink" href={`/work-mode?project=${current.project.id}`}>Open Work assignment ↗</Link></>}</section></div>
 <p className="scorpio8a-disclaimer">Approve and continue creates a NEW bounded Work run. No automatic checkpoint resume, silent terminal access or host permission grant is available.</p></div>;
}

export function ScorpioPermissions(){const {overview,error,loading}=useScorpioActivity();const perms=overview?.permissions??{};const labels:Record<string,string>={public_research:"Bounded public research",owner_uploaded_files:"Owner-selected uploaded files",python_engineering:"Isolated Python engineering",host_shell:"Host terminal",host_file_scan:"Unapproved host directories",arbitrary_browser:"Unrestricted browser automation"};return <div className="scorpio8a-page"><ScorpioPageHeading title="Tools & permissions" description="Read-only inventory of capabilities enforced by the Work API. This panel never changes grants."/>{error&&<p role="alert" className="scorpio8a-error">{error}</p>}<div className="scorpio8a-card"><h3>Backend capabilities</h3>{loading&&<p>Checking backend permissions…</p>}{Object.keys(perms).map(k=><div key={k} className="scorpio8a-permission"><span><strong>{labels[k]??k}</strong><small>{k}</small></span><span className={perms[k]?"scorpio8a-allowed":"scorpio8a-denied"}>{perms[k]?"Available":"Unavailable"}</span></div>)}<p className="scorpio8a-disclaimer">Changing workstation access requires a separately implemented and authenticated backend permission process. Scorpio does not display nonfunctional grant toggles.</p></div><Link className="scorpio8a-inlineLink" href="/approvals">Review existing Work cases ↗</Link></div>}

export function ScorpioHealth(){const {overview,error,entries,loading,refresh}=useScorpioActivity();const [assistant,setAssistant]=useState<{configured?:boolean;local_reachable?:boolean;local_model?:string|null}|null>(null);useEffect(()=>{let live=true;void mioApi<{configured:boolean;local_reachable:boolean;local_model:string|null}>("assistant/status").then(v=>{if(live)setAssistant(v)}).catch(()=>{if(live)setAssistant(null)});return()=>{live=false};},[]);const active=entries.filter(e=>["running","queued"].includes(e.summary.state)).length;return <div className="scorpio8a-page"><ScorpioPageHeading title="System health" description="Work API responses and model status from real authenticated endpoints. No synthetic CPU, GPU or memory readings." action={<button onClick={refresh} className="scorpio8a-button">Refresh</button>}/>{error&&<p className="scorpio8a-error">{error}</p>}<div className="scorpio8a-statGrid"><div className="scorpio8a-card"><small>WORK API</small><strong>{overview?"Connected":loading?"Checking":"Unavailable"}</strong></div><div className="scorpio8a-card"><small>ACTIVE WORK TASKS</small><strong>{loading?"—":active}</strong></div><div className="scorpio8a-card"><small>LOCAL MODEL CONFIGURED</small><strong>{assistant?assistant.configured?"Yes":"No":"Unknown"}</strong></div><div className="scorpio8a-card"><small>MODEL REACHABLE</small><strong>{assistant?assistant.local_reachable?"Yes":"No":"Unknown"}</strong></div></div><div className="scorpio8a-card"><h3>Service boundaries</h3><p>API, worker, dashboard, ComfyUI and Ollama are separate managed processes. A responsive Work API does not establish every process is healthy. Only measured states are reported here.</p><p className="scorpio8a-meta">Configured local model: {assistant?.local_model||"None reported"}</p><p className="scorpio8a-disclaimer">Restart actions are intentionally not exposed. Service management requires separately authorized identity-checked tools and health verification.</p></div></div>}

export function ScorpioActivity(){const {entries,error,loading,refresh}=useScorpioActivity();const [focus,setFocus]=useState<string|null>(null);const [run,setRun]=useState<WorkRun|null>(null);useEffect(()=>{if(!focus){setRun(null);return;}let mounted=true;void mioApi<WorkRun>(`work/runs/${focus}`).then(v=>{if(mounted)setRun(v)}).catch(()=>{if(mounted)setRun(null)});return()=>{mounted=false};},[focus]);return <div className="scorpio8a-page"><ScorpioPageHeading title="Logs & events" description="Saved Work events and task outcomes. Browser-visible log entries are from the authenticated Work database." action={<button className="scorpio8a-button" onClick={refresh}>Refresh logs</button>}/>{error&&<p className="scorpio8a-error">{error}</p>}<div className="scorpio8a-panelGrid"><section className="scorpio8a-card"><h3>Saved runs ({entries.length})</h3>{loading&&<p>Loading…</p>}{entries.map(e=><button key={e.summary.id} className="scorpio8a-queueRow" onClick={()=>setFocus(e.summary.id)}><span><strong>{e.summary.prompt.slice(0,80)}</strong><small>{e.project.title}</small></span><em>{stateName(e.summary.state)}</em></button>)}</section><section className="scorpio8a-card"><h3>Audit timeline</h3>{!run&&<p>Choose a run to inspect its audit timeline.</p>}{run&&<>{run.error&&<p className="scorpio8a-error">{run.error}</p>}{run.events.map((event,i)=><div key={i} className="scorpio8a-event"><small>{new Date(event.created*1000).toLocaleString()}</small><strong>{event.phase}</strong><p>{event.detail}</p></div>)}</>}</section></div></div>}

export function ScorpioSettings(){return <div className="scorpio8a-page"><ScorpioPageHeading title="Settings" description="Owner guidance for the current local-first Scorpio deployment."/><section className="scorpio8a-card"><h3>Scorpio identity</h3><p>Scorpio is the dashboard name and scorpion logo. The underlying MioAgent backend, API paths, SQLite stores, operating services and repository remain unchanged for compatibility.</p><h3>Data and permissions</h3><p>Chat history, project files, memory and Work results remain in their existing backend data stores. Removing them uses the authenticated controls in their respective pages.</p><h3>Automation and approvals</h3><p>Work runs need owner authorization for guarded tasks. Review requests currently create new bounded tasks, not an automatic checkpoint resume. Persistent machine-control grants are disabled.</p><Link href="/tools-permissions" className="scorpio8a-inlineLink">View verified capabilities ↗</Link></section></div>}
