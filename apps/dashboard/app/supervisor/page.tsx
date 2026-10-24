"use client";
import {useCallback,useEffect,useState} from "react";
import Link from "next/link";
import {mioApi,postJson,type WorkProject} from "../_mio/api";
import "../_mio/scorpio9a.css";

type PlanRow={id:string;project:string;goal:string;state:string;created:number;updated:number};
type Step={id:string;position:number;prompt:string;state:string;run_id:string|null};
type Plan=PlanRow&{steps:Step[];events:{phase:string;detail:string;created:number}[]};
const states:Record<string,string>={draft:"Needs owner approval",ready:"Awaiting worker",running:"Executing bounded steps",paused:"Future steps paused",attention:"Owner review required",complete:"All steps answered"};
export default function SupervisorPage(){
 const [projects,setProjects]=useState<WorkProject[]>([]),[plans,setPlans]=useState<PlanRow[]>([]);
 const [selected,setSelected]=useState(""),[detail,setDetail]=useState<Plan|null>(null);
 const [project,setProject]=useState(""),[goal,setGoal]=useState("");
 const [steps,setSteps]=useState(""),[approved,setApproved]=useState(false);
 const [error,setError]=useState(""),[busy,setBusy]=useState(false);
 const refresh=useCallback(async()=>{
  try{const [a,b]=await Promise.all([mioApi<{projects:WorkProject[]}>("work/overview"),mioApi<{plans:PlanRow[]}>("supervisor/plans")]);
   setProjects(a.projects);setPlans(b.plans);setProject(x=>x||a.projects[0]?.id||"");setSelected(x=>x||b.plans[0]?.id||"");setError("");
  }catch(e){setError(e instanceof Error?e.message:"Supervisor API unavailable")}
 },[]);
 useEffect(()=>{void refresh();const tick=window.setInterval(()=>void refresh(),5000);return()=>window.clearInterval(tick)},[refresh]);
 useEffect(()=>{if(!selected){setDetail(null);return}let live=true;const get=async()=>{try{const p=await mioApi<Plan>(`supervisor/plans/${selected}`);if(live)setDetail(p)}catch(e){if(live)setError(e instanceof Error?e.message:"Plan unavailable")}};void get();const t=window.setInterval(()=>void get(),5000);return()=>{live=false;window.clearInterval(t)}},[selected]);
 const perform=async(task:()=>Promise<Plan>)=>{setBusy(true);try{const item=await task();setSelected(item.id);setDetail(item);setApproved(false);setError("");await refresh()}catch(e){setError(e instanceof Error?e.message:"Request failed")}finally{setBusy(false)}};
 const draft=()=>{const list=steps.split("\n").map(s=>s.trim()).filter(Boolean);void perform(()=>mioApi<Plan>("supervisor/plans",postJson({project_id:project,goal,steps:list})))};
 const propose=()=>void perform(()=>mioApi<Plan>("supervisor/propose",postJson({project_id:project,goal})));
 return <main className="sc9-page"><header className="sc9-heading"><div><span>SCORPIO / SUPERVISOR · 9A</span><h2>Owner-approved autonomous task chains</h2><p>Create a bounded plan, inspect its steps, then approve execution. The independent Work worker dispatches one step at a time.</p></div><button onClick={()=>void refresh()}>Refresh</button></header>
 {error&&<p className="sc9-alert" role="alert">{error}</p>}
 <div className="sc9-columns"><section className="sc9-card"><h3>Draft task chain</h3><label>Existing Work project<select value={project} onChange={e=>setProject(e.target.value)}><option value="">Select a project</option>{projects.map(p=><option key={p.id} value={p.id}>{p.title}</option>)}</select></label>
 <label>Overall goal<textarea value={goal} onChange={e=>setGoal(e.target.value)} maxLength={1800} rows={3} placeholder="Describe the desired outcome"/></label>
 <label>Owner-reviewed bounded steps, one per line (1–6)<textarea value={steps} onChange={e=>setSteps(e.target.value)} rows={6} placeholder="Research the question with cited evidence\nSummarize findings and limitations"/></label>
 <button disabled={busy||!project||goal.trim().length<10} onClick={propose}>Suggest draft with local model</button><button disabled={busy||!project||goal.trim().length<10||steps.trim().length<8} onClick={draft}>Save draft — no execution</button><p className="sc9-note">This initial release does not let the model invent new tasks or gain shell access. All steps require your explicit review before any automatic scheduling.</p>
 <Link href="/projects-space">Create a Work project if none exists ↗</Link></section>
 <section className="sc9-card"><h3>Saved supervisor plans</h3>{!plans.length&&<p>No supervisor plans saved. Work data is read from the native Work database.</p>}{plans.map(p=><button key={p.id} className={`sc9-plan ${selected===p.id?"selected":""}`} onClick={()=>{setSelected(p.id);setApproved(false)}}><strong>{p.goal}</strong><small>{states[p.state]||p.state} · {p.id.slice(0,8)}</small></button>)}</section></div>
 {detail&&<section className="sc9-card sc9-detail"><div className="sc9-detailHeader"><div><h3>Plan {detail.id.slice(0,8)}</h3><p>{detail.goal}</p><small>Status: {states[detail.state]||detail.state}</small></div><div className="sc9-actions">{["draft","paused"].includes(detail.state)&&<label className="sc9-check"><input type="checkbox" checked={approved} onChange={e=>setApproved(e.target.checked)}/>I reviewed all bounded steps and approve their sequential execution</label>}{["draft","paused"].includes(detail.state)&&<button disabled={busy||!approved} onClick={()=>void perform(()=>mioApi<Plan>(`supervisor/plans/${detail.id}/approve`,postJson({approved:true})))}>Approve and run</button>}{["ready","running"].includes(detail.state)&&<button disabled={busy} onClick={()=>void perform(()=>mioApi<Plan>(`supervisor/plans/${detail.id}/pause`,{method:"POST"}))}>Pause future steps</button>}</div></div>
 <div className="sc9-steps">{detail.steps.map(s=><div key={s.id}><strong>{s.position+1}. {s.prompt}</strong><small>{s.state} {s.run_id&&<Link href={`/control-room?project=${detail.project}&run=${s.run_id}`}> · View Work evidence ↗</Link>}</small></div>)}</div>
 <details><summary>Recorded supervisor decisions</summary>{detail.events.map((e,i)=><p key={i}>{e.phase}: {e.detail}</p>)}</details><p className="sc9-note">Failed, interrupted or needs-review runs stop the plan. No automatic retries, arbitrary terminal commands, self-deployment or permission grants.</p></section>}
 </main>
}
