"use client";
import { useCallback, useEffect, useState } from "react";
import UIShell from "../_mio/ui-shell";
import RichText from "../_mio/rich-text";
import { delegationTitle, done, isDelegation, mioApi, postJson, type WorkProject, type WorkProjectDetail, type WorkRun } from "../_mio/api";
import s from "../_mio/experience.module.css";

type Capability = {host_shell:boolean;host_file_scan:boolean;arbitrary_browser:boolean;public_research:boolean;owner_uploaded_files:boolean};
type WorkOverview = {projects:WorkProject[];permissions:Capability};
const blockNames = ["Host terminal", "Unapproved folders", "Browser automation", "Self-directed code execution"];

export default function WorkMode(){
  const [overview,setOverview]=useState<WorkOverview|null>(null);
  const [selected,setSelected]=useState<string|null>(null);
  const [detail,setDetail]=useState<WorkProjectDetail|null>(null);
  const [run,setRun]=useState<WorkRun|null>(null);
  const [create,setCreate]=useState(false);
  const [title,setTitle]=useState("");const [goal,setGoal]=useState("");const [acceptance,setAcceptance]=useState("");
  const [kind,setKind]=useState<"supported"|"computer">("supported");
  const [ack,setAck]=useState(false);const [busy,setBusy]=useState(false);const [error,setError]=useState("");
  const refresh=useCallback(async()=>{
    const next=await mioApi<WorkOverview>("work/overview");setOverview(next);
    setSelected(old=>old??next.projects.find(p=>isDelegation(p.title))?.id??null);
  },[]);
  useEffect(()=>{const params=new URLSearchParams(window.location.search);const project=params.get("project");if(project && /^[0-9a-f]{32}$/.test(project))setSelected(project);void refresh().catch((e:Error)=>setError(e.message));},[refresh]);
  useEffect(()=>{
    if(!selected){setDetail(null);setRun(null);return;}
    let active=true;
    const tick=async()=>{
      try{
        const fresh=await mioApi<WorkProjectDetail>(`work/projects/${selected}`);
        if(active)setDetail(fresh);
        const last=fresh.runs[0];
        if(last){const current=await mioApi<WorkRun>(`work/runs/${last.id}`);if(active)setRun(current);}else if(active)setRun(null);
      }catch(e){if(active)setError(e instanceof Error?e.message:"Work history unavailable");}
    };
    void tick();const timer=setInterval(()=>void tick(),3300);return()=>{active=false;clearInterval(timer);};
  },[selected]);
  const jobs=overview?.projects.filter(p=>isDelegation(p.title))??[];
  const canStart=kind==="supported"&&ack&&goal.trim().length>=8&&title.trim().length>=3&&acceptance.trim().length>=8&&!busy&&overview?.permissions.public_research===true;
  async function delegate(){
    if(!canStart)return;
    setBusy(true);setError("");
    try{
      const instructions=["Owner-delegated bounded task; not authorized for terminal/browser/host folders.","Desired outcome:",goal.trim(),"Acceptance criteria:",acceptance.trim(),"Stop if requested capabilities are not available; do not claim unsupported work succeeded."].join("\n");
      const task=await mioApi<WorkProject>("work/projects",postJson({title:delegationTitle(title.trim()),instructions:instructions.slice(0,6000)}));
      setSelected(task.id);setCreate(false);await refresh();
      const request=`${goal.trim()}\n\nAcceptance criteria: ${acceptance.trim()}\nUse only available authorized tools. Report unsupported steps explicitly.`;
      try{await mioApi(`work/projects/${task.id}/runs`,postJson({prompt:request.slice(0,6000)}));}
      catch(e){setError(`Work item saved, but task did not start: ${e instanceof Error?e.message:"Unknown error"}`);}
      setTitle("");setGoal("");setAcceptance("");setAck(false);
    }catch(e){setError(e instanceof Error?e.message:"Could not create Work assignment");}
    finally{setBusy(false);}
  }
  return <UIShell section="work" title="Work" subtitle="Delegate supported tasks and inspect real execution evidence">
    <section className={s.stage}>
      <div className={s.split}>
        <aside className={s.panel}><div className={s.panelTop}><span className={s.panelTitle}>WORK ASSIGNMENTS</span><button className={s.iconButton} onClick={()=>setCreate(true)}>＋ New</button></div>
          {jobs.map(job=><button key={job.id} className={`${s.listButton} ${selected===job.id?s.selected:""}`} onClick={()=>setSelected(job.id)}>{job.title.replace(/^Work · /,"")}</button>)}
          {!jobs.length&&<p className={s.hint}>Delegated jobs appear here and remain saved after closing the browser.</p>}
        </aside>
        <div className={s.body}>
          {!selected?<div className={s.centered}><span className={s.welcomeIcon}>✳</span><h2>Give work to MioAgent.</h2><p>Define the goal and acceptance criteria. MioAgent will execute tasks supported by its current permissions and record the outcome.</p><button className={s.primary} onClick={()=>setCreate(true)}>New Work assignment</button><div className={s.safety}>Autonomous engineering and permissioned computer access are not yet installed. Work currently supports bounded research, drafts and linked-file analysis.</div></div>:<>
            <div className={s.heading}><div className={s.pillRow} style={{justifyContent:"space-between"}}><div><h2>{detail?.title.replace(/^Work · /,"")||"Loading assignment…"}</h2><p>Server-backed activity · Saved in private SQLite</p></div><a className={s.secondary} href={`/control-room?project=${selected}`}>View Control Room ↗</a></div></div>
            <div className={s.scroll}><div className={s.narrow}>
              <div className={s.notice}><strong>Work engine status:</strong> tasks remain active after browser disconnection while FastAPI is running. If the API process restarts, unfinished tasks are recorded as interrupted; no automatic resume is implemented yet.</div>
              {run?<><div className={s.card}><div className={s.pillRow} style={{justifyContent:"space-between"}}><strong>Supervisor record</strong><span className={`${s.state} ${["needs_review","interrupted"].includes(run.state)?s.warning:run.state==="failed"?s.failed:""}`}>{run.state.replaceAll("_"," ")}</span></div><p style={{marginTop:12,whiteSpace:"pre-wrap"}}>{run.prompt}</p></div><div className={s.card}><h3>Actual steps</h3><div className={s.timeline}>{run.events.map((event,i)=><div key={`${event.phase}-${i}`} className={s.event}><strong>{event.phase}</strong><div>{event.detail}</div></div>)}</div>{!done(run.state)&&<span className={s.loading}>Task is active in the API process. This timeline refreshes automatically.</span>}</div>{run.result&&<div className={s.card}><h3>Outcome</h3><RichText text={run.result}/><a className={s.download} href={`/api/proxy/work/runs/${run.id}/artifact`} target="_blank" rel="noopener noreferrer">Open result ↗</a></div>}{run.error&&<div className={s.error}>{run.error}</div>}{run.sources.length>0&&<div className={s.card}><h3>Sources</h3>{run.sources.map(x=><a className={s.source} key={x.ref} target="_blank" rel="noopener noreferrer" href={x.url}>[{x.ref}] {x.title}</a>)}<p className={s.hint}>Publication metadata and search snippets are not verified full-page research.</p></div>}</>:<div className={s.notice}>This assignment has no run. If creation was interrupted, start a new assignment after reviewing the error below.</div>}
              <div className={s.card}><h3>Capabilities & restrictions</h3><div className={s.kv}><span>Public research</span><strong>{overview?.permissions.public_research?"Available":"Unavailable"}</strong></div><div className={s.kv}><span>Approved uploaded files</span><strong>{overview?.permissions.owner_uploaded_files?"Available":"Unavailable"}</strong></div>{blockNames.map(t=><div key={t} className={s.kv}><span>{t}</span><strong>Not enabled</strong></div>)}<p className={s.hint}>These are backend-enforced restrictions, not visual switches.</p></div>
              {error&&<p className={s.error}>{error}</p>}
            </div></div>
          </>}
        </div>
      </div>
      {create&&<aside className={s.pane} role="dialog" aria-label="New Work assignment"><div className={s.paneHeader}><h3>Delegate a task</h3><button className={s.iconButton} onClick={()=>setCreate(false)}>✕</button></div><p className={s.notice}>Work is a distinct user workflow with its own assignments. The current release still shares the private Work database; isolated autonomous job storage is planned.</p>
        <label className={s.field}>Assignment title<input value={title} maxLength={110} onChange={e=>setTitle(e.target.value)} placeholder="e.g. Robotics research brief" /></label>
        <label className={s.field}>What should be delivered?<textarea value={goal} onChange={e=>setGoal(e.target.value)} maxLength={3300} placeholder="Describe the outcome, not only the question" /></label>
        <label className={s.field}>How will you verify success?<textarea value={acceptance} maxLength={1600} onChange={e=>setAcceptance(e.target.value)} placeholder="Specific acceptance criteria" /></label>
        <div className={s.card}><h3>Required access</h3><label className={s.listItem}><input type="radio" name="kind" checked={kind==="supported"} onChange={()=>setKind("supported")}/> Research / writing / owner-attached documents</label><label className={s.listItem}><input type="radio" name="kind" checked={kind==="computer"} onChange={()=>setKind("computer")}/> Browser, terminal or workstation files</label>{kind==="computer"&&<p className={s.safety}>This task requires a future permissioned supervisor service. Starting it is disabled rather than pretending computer access exists.</p>}</div>
        <label className={s.listItem}><input type="checkbox" checked={ack} onChange={e=>setAck(e.target.checked)}/> I authorize the available bounded tools for this task. No host computer permissions are granted.</label>
        <button className={s.primary} disabled={!canStart} onClick={()=>void delegate()}>{busy?"Submitting…":kind==="computer"?"Computer tools not yet available":"Start bounded Work"}</button>
        <p className={s.hint}>The task runs server-side while the API stays running; automatic recovery after restart and user notifications require the next backend phase.</p>
        {error&&<p className={s.error}>{error}</p>}
      </aside>}
    </section>
  </UIShell>;
}
