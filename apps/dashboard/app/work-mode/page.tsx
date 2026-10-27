"use client";
import { useCallback, useEffect, useState } from "react";
import UIShell from "../_mio/ui-shell";
import RichText from "../_mio/rich-text";
import ScorpioApprovalPanel from "../_mio/scorpio-approval-panel";
import ScorpioBrowserEvidence from "../_mio/scorpio-browser-evidence";
import { delegationTitle, done, isDelegation, mioApi, postJson, type WorkProject, type WorkProjectDetail, type WorkRun } from "../_mio/api";
import s from "../_mio/experience.module.css";
import { WorkImageComposer } from "../_mio/omni-image";

type Capability = {host_shell:boolean;host_file_scan:boolean;arbitrary_browser:boolean;public_research:boolean;owner_uploaded_files:boolean;python_engineering:boolean};
type WorkOverview = {projects:WorkProject[];permissions:Capability};
const blockNames = ["Host terminal", "Unapproved folders", "Browser automation", "Self-directed code execution"];

export default function WorkMode(){
  const [overview,setOverview]=useState<WorkOverview|null>(null);
  const [showArchived,setShowArchived]=useState(false);
  const [selected,setSelected]=useState<string|null>(null);
  const [detail,setDetail]=useState<WorkProjectDetail|null>(null);
  const [run,setRun]=useState<WorkRun|null>(null);
  const [create,setCreate]=useState(false);
  const [goal,setGoal]=useState("");
  const [busy,setBusy]=useState(false);const [error,setError]=useState("");
  const refresh=useCallback(async()=>{
    const next=await mioApi<WorkOverview>(`work/overview?archived=${showArchived}`);setOverview(next);
    setSelected(old=>next.projects.some(p=>p.id===old&&isDelegation(p.title))?old:next.projects.find(p=>isDelegation(p.title))?.id??null);
  },[showArchived]);
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
  async function assignmentAction(action:"archive"|"restore"|"delete"){
    if(!selected||busy)return;
    if(action==="delete" && !window.confirm("Permanently delete this Work assignment, recorded events and resulting drafts from the Scorpio backend? This cannot be undone."))return;
    setBusy(true);setError("");
    try{
      const changed=await mioApi<{artifacts_cleanup_incomplete?:string[]}>(`work/projects/${selected}${action==="delete"?"":`/${action}`}`, {method:action==="delete"?"DELETE":"POST"});
      if(changed.artifacts_cleanup_incomplete?.length)setError("Engineering artifact cleanup incomplete; inspect private server storage.");
      setSelected(null);setRun(null);setDetail(null);await refresh();
    }catch(e){setError(e instanceof Error?e.message:"Work assignment could not be updated");}finally{setBusy(false);}
  }
  const jobs=overview?.projects.filter(p=>isDelegation(p.title))??[];
  // Only the requested outcome is user-authored; backend task authorization still
  // requires an explicit owner click on Approve below.
  const engineeringGoal = /^SCORPIO9D1 TEXTUTILS: /i.test(goal.trim())
    || /\b(build|implement|write|create|fix|develop|debug)\b.{0,140}\b(python|script|code|library|program|calculator|application)\b/i.test(goal);
  const unsupportedGoal = /\b(unrestricted|host terminal|shell access|browser automation|control my computer|arbitrary folders)\b/i.test(goal);
  const proposedType = engineeringGoal ? "engineering" : "bounded";
  const canStart = !busy && !unsupportedGoal && goal.trim().length >= 8 &&
    (engineeringGoal ? overview?.permissions.python_engineering === true : overview?.permissions.public_research === true);
  async function delegate(){
    if(!canStart)return;
    setBusy(true);setError("");
    try{
      const acceptedGoal = goal.trim();
      const automaticAcceptance = engineeringGoal
        ? "Deliver a private source artifact; run the platform's independent sandbox tests and mark unverified work for review."
        : "Produce a grounded answer within already permitted tools; flag unsupported or unverified claims.";
      const instructions = ["Owner-directed task. No host shell, browser or unapproved files.",
        "Goal:", acceptedGoal, "System-generated acceptance:", automaticAcceptance].join("\n");
      const automaticTitle = acceptedGoal.split("\n")[0].slice(0, 100);
      const task=await mioApi<WorkProject>("work/projects",postJson({title:delegationTitle(automaticTitle),instructions:instructions.slice(0,6000)}));
      setSelected(task.id);setCreate(false);if(showArchived)setShowArchived(false);else await refresh();
      // Preserve the exact prefix for pinned engineering contracts; avoid
      // appending repetitive acceptance prose to the model's input.
      const textutilsGoal = proposedType === "engineering" &&
        ["normalize_whitespace", "count_words", "is_palindrome", "slugify"]
          .every(name => acceptedGoal.includes(name));
      const request = textutilsGoal && !acceptedGoal.startsWith("SCORPIO9D1 TEXTUTILS: ")
        ? `SCORPIO9D1 TEXTUTILS: ${acceptedGoal}` : acceptedGoal;
      try{await mioApi(`work/projects/${task.id}/runs`,postJson({prompt:request.slice(0,6000),task_type:proposedType,approved:true}));}
      catch(e){setError(`Work item saved, but task did not start: ${e instanceof Error?e.message:"Unknown error"}`);}
      setGoal("");
    }catch(e){setError(e instanceof Error?e.message:"Could not create Work assignment");}
    finally{setBusy(false);}
  }
  return <UIShell section="work" title="Work" subtitle="Delegate supported tasks and inspect real execution evidence">
    <section className={s.stage}>
      <div className={s.split}>
        <aside className={s.panel}><div className={s.panelTop}><span className={s.panelTitle}>WORK ASSIGNMENTS</span><button className={s.iconButton} onClick={()=>setCreate(true)}>＋ New</button></div>
          <button className={s.iconButton} onClick={()=>{setSelected(null);setShowArchived(v=>!v);}}>{showArchived?"← Active assignments":"Archived assignments"}</button>
          {jobs.map(job=><button key={job.id} className={`${s.listButton} ${selected===job.id?s.selected:""}`} onClick={()=>setSelected(job.id)}>{job.title.replace(/^Work · /,"")}</button>)}
          {!jobs.length&&<p className={s.hint}>Delegated jobs appear here and remain saved after closing the browser.</p>}
        </aside>
        <div className={s.body}>
          {!selected?<div className={s.centered}><span className={s.welcomeIcon}>✳</span><h2>Give work to Scorpio.</h2><p>Tell Scorpio what you want once. Scorpio proposes the supported work type and fills in the technical acceptance checks. You only approve or reject.</p><button className={s.primary} onClick={()=>setCreate(true)}>New Work assignment</button><div className={s.safety}>Isolated Python engineering and bounded research are available. Unrestricted host terminal, browser automation and arbitrary folder access remain disabled.</div></div>:<>
            <div className={s.heading}><div className={s.pillRow} style={{justifyContent:"space-between"}}><div><h2>{detail?.title.replace(/^Work · /,"")||"Loading assignment…"}</h2><p>Server-backed activity · Saved in private SQLite</p></div><div className={s.pillRow}>
                <a className={s.secondary} href={`/control-room?project=${selected}`}>Control Room ↗</a>
                <button className={s.iconButton} disabled={busy} onClick={()=>void assignmentAction(showArchived?"restore":"archive")}>{showArchived?"Restore":"Archive"}</button>
                <button className={s.iconButton} disabled={busy} onClick={()=>void assignmentAction("delete")}>Delete</button>
              </div></div></div>
            <div className={s.scroll}><div className={s.narrow}>
              <div className={s.notice}><strong>Work engine status:</strong> bounded tasks are processed by the independent Ubuntu Work worker after browser disconnection, including during API restarts. Worker failure may interrupt an active task; automatic checkpointed resume and autonomous computer tools are not installed.</div>
              {run?<><div className={s.card}><div className={s.pillRow} style={{justifyContent:"space-between"}}><strong>Supervisor record</strong><span className={`${s.state} ${["needs_review","interrupted"].includes(run.state)?s.warning:run.state==="failed"?s.failed:""}`}>{run.state.replaceAll("_"," ")}</span></div><details className={s.hint}><summary>Show task instructions</summary><p style={{whiteSpace:"pre-wrap"}}>{run.prompt}</p></details></div><div className={s.card}><details><summary>View technical execution events</summary><div className={s.timeline}>{run.events.map((event,i)=><div key={`${event.phase}-${i}`} className={s.event}><strong>{event.phase}</strong><div>{event.detail}</div></div>)}</div></details>{!done(run.state)&&<span className={s.loading}>The Ubuntu worker owns this task. The timeline refreshes automatically.</span>}</div>{run.result&&<div className={s.card}><h3>Outcome</h3><RichText text={run.result}/>{run.mode==="engineering"&&<><p className={s.hint}>Source files are stored privately. Verified tests are reported in the worker timeline; unverified drafts remain marked needs review.</p><a className={s.download} href={`/api/proxy/work/runs/${run.id}/download`}>Download generated source ZIP ↗</a></>}<a className={s.download} href={`/api/proxy/work/runs/${run.id}/artifact`} target="_blank" rel="noopener noreferrer">Open result ↗</a></div>}<ScorpioApprovalPanel projectId={selected} run={run} onSubmitted={(id)=>window.location.assign(`/control-room?project=${selected}&run=${id}`)}/>{run.error&&<div className={s.error}>{run.error}</div>}{run.sources.length>0&&<div className={s.card}><h3>Sources</h3>{run.sources.map(x=><a className={s.source} key={x.ref} target="_blank" rel="noopener noreferrer" href={x.url}>[{x.ref}] {x.title}</a>)}<p className={s.hint}>Publication metadata and search snippets are not verified full-page research.</p></div>}</>:<div className={s.notice}>This assignment has no run. If creation was interrupted, start a new assignment after reviewing the error below.</div>}
              <div className={s.card}><h3>Capabilities & restrictions</h3><div className={s.kv}><span>Public research</span><strong>{overview?.permissions.public_research?"Available":"Unavailable"}</strong></div><div className={s.kv}><span>Approved uploaded files</span><strong>{overview?.permissions.owner_uploaded_files?"Available":"Unavailable"}</strong></div>{blockNames.map(t=><div key={t} className={s.kv}><span>{t}</span><strong>Not enabled</strong></div>)}<p className={s.hint}>These are backend-enforced restrictions, not visual switches.</p></div>
              {selected&&<ScorpioBrowserEvidence key={selected} projectId={selected} run={run}/>}
              {selected&&<WorkImageComposer key={selected} scope="work" scopeId={selected}/>}
              {error&&<p className={s.error}>{error}</p>}
            </div></div>
          </>}
        </div>
      </div>
      {create&&<aside className={s.pane} role="dialog" aria-label="New Work assignment"><div className={s.paneHeader}><h3>Delegate a task</h3><button className={s.iconButton} onClick={()=>setCreate(false)}>✕</button></div><p className={s.notice}>Work is a distinct user workflow with its own assignments. The current release still shares the private Work database; isolated autonomous job storage is planned.</p>
        <label className={s.field}>What would you like Scorpio to do?<textarea value={goal} onChange={e=>setGoal(e.target.value)} maxLength={3300} placeholder="e.g. Build a Python text utilities library" /></label>
        <p className={s.hint}>Title, acceptance checks and bounded work mode are proposed automatically. No extra description required.</p>
<div className={s.card}><h3>Scorpio proposes</h3>
          <p>{unsupportedGoal ? "Requires unavailable computer permissions — cannot start" :
            engineeringGoal ? "Python engineering — private files and isolated tests" : "Bounded research or writing"}</p>
          <p className={s.hint}>Scorpio will create the title and acceptance checks automatically. It will not gain host terminal, browser or arbitrary file access.</p>
        </div>
        <div className={s.pillRow}>
          <button className={s.primary} disabled={!canStart} onClick={()=>void delegate()}>{busy?"Submitting…":"Approve & start"}</button>
          <button className={s.iconButton} disabled={busy} onClick={()=>{setCreate(false);setGoal("");}}>Reject — do nothing</button>
        </div>
        <p className={s.hint}>The independent Ubuntu worker handles bounded tasks. Approved Python source creation is isolated to private Work artifacts. Tests require a verified Bubblewrap sandbox; automatic checkpointed resume is planned.</p>
        {error&&<p className={s.error}>{error}</p>}
      </aside>}
    </section>
  </UIShell>;
}
