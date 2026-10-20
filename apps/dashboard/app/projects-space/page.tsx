"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import UIShell from "../_mio/ui-shell";
import RichText from "../_mio/rich-text";
import { done, isDelegation, mioApi, postJson, type WorkProject, type WorkProjectDetail, type WorkRun } from "../_mio/api";
import s from "../_mio/experience.module.css";

const MAX_FILE=8*1024*1024;
async function fileBase64(file:File){
  if(file.size===0||file.size>MAX_FILE)throw new Error(`${file.name}: maximum size 8 MiB`);
  const bytes=new Uint8Array(await file.arrayBuffer());let data="";
  for(let i=0;i<bytes.length;i+=8192)data+=String.fromCharCode(...bytes.subarray(i,i+8192));
  return btoa(data);
}

export default function ProjectsSpace(){
  const [projects,setProjects]=useState<WorkProject[]>([]);
  const [id,setId]=useState<string|null>(null);
  const [detail,setDetail]=useState<WorkProjectDetail|null>(null);
  const [runs,setRuns]=useState<Record<string,WorkRun>>({});
  const [prompt,setPrompt]=useState("");const [name,setName]=useState("");const [instructions,setInstructions]=useState("");
  const [create,setCreate]=useState(false);const [knowledge,setKnowledge]=useState(false);
  const [memory,setMemory]=useState("");const [busy,setBusy]=useState(false);const [error,setError]=useState("");
  const upload=useRef<HTMLInputElement>(null);const bottom=useRef<HTMLDivElement>(null);
  const refresh=useCallback(async()=>{
    const next=await mioApi<{projects:WorkProject[]}>("work/overview");
    const visible=next.projects.filter(p=>!isDelegation(p.title));
    setProjects(visible);setId(old=>old??visible[0]?.id??null);
  },[]);
  const load=useCallback(async(project:string)=>{
    const info=await mioApi<WorkProjectDetail>(`work/projects/${project}`);
    setDetail(info);
  },[]);
  useEffect(()=>{void refresh().catch((e:Error)=>setError(e.message));},[refresh]);
  useEffect(()=>{if(!id){setDetail(null);setRuns({});return;}setRuns({});setDetail(null);void load(id).catch((e:Error)=>setError(e.message));},[id,load]);
  useEffect(()=>{
    if(!id||!detail||detail.id!==id)return;
    let active=true;
    const poll=async()=>{
      try{
        const fresh=await mioApi<WorkProjectDetail>(`work/projects/${id}`);
        if(!active)return;
        setDetail(fresh);
        const results=await Promise.all(fresh.runs.slice(0,16).map(r=>mioApi<WorkRun>(`work/runs/${r.id}`)));
        if(active)setRuns(Object.fromEntries(results.map(r=>[r.id,r])));
      }catch(e){if(active)setError(e instanceof Error?e.message:"Project update unavailable");}
    };
    void poll();const timer=setInterval(()=>void poll(),5000);
    return()=>{active=false;clearInterval(timer);};
  },[id,detail?.id]);
  useEffect(()=>{bottom.current?.scrollIntoView({behavior:"smooth",block:"end"});},[detail?.runs.length,runs]);
  async function newProject(){
    if(busy||name.trim().length<3)return;
    setBusy(true);setError("");
    try{const p=await mioApi<WorkProject>("work/projects",postJson({title:name.trim(),instructions:instructions.trim()}));setName("");setInstructions("");setCreate(false);setId(p.id);await refresh();}
    catch(e){setError(e instanceof Error?e.message:"Project creation failed");}finally{setBusy(false);}
  }
  async function send(){
    if(!id||busy||prompt.trim().length<4)return;
    setBusy(true);setError("");
    try{await mioApi(`work/projects/${id}/runs`,postJson({prompt:prompt.trim()}));setPrompt("");await load(id);}
    catch(e){setError(e instanceof Error?e.message:"Cannot send project task");}finally{setBusy(false);}
  }
  async function attach(files:FileList|null){
    if(!id||!files?.length||busy)return;
    setBusy(true);setError("");
    try{
      if(files.length>6)throw new Error("Add at most six files at once");
      for(const file of Array.from(files)){
        const saved=await mioApi<{id:string}>("studio/attachments",postJson({filename:file.name,base64:await fileBase64(file)}));
        await mioApi(`work/projects/${id}/files`,postJson({attachment_id:saved.id}));
      }
      await load(id);setKnowledge(true);
    }catch(e){setError(e instanceof Error?e.message:"Could not attach files");}
    finally{if(upload.current)upload.current.value="";setBusy(false);}
  }
  async function remember(){
    if(!id||busy||memory.trim().length<3)return;
    setBusy(true);setError("");
    try{await mioApi(`work/projects/${id}/memory`,postJson({content:memory.trim(),approved:true}));setMemory("");await load(id);}
    catch(e){setError(e instanceof Error?e.message:"Could not save project memory");}finally{setBusy(false);}
  }
  async function removeMemory(memoryId:string){
    if(!id||busy)return;setBusy(true);
    try{await mioApi(`work/projects/${id}/memory/${memoryId}`,{method:"DELETE"});await load(id);}
    catch(e){setError(e instanceof Error?e.message:"Could not remove memory");}finally{setBusy(false);}
  }
  const items=detail?.runs.slice(0,16).reverse()??[];
  return <UIShell section="projects" title="Projects" subtitle="Ongoing conversations with shared instructions and files">
    <div className={s.stage}>
      <div className={s.split}>
        <aside className={s.panel} aria-label="Project list"><div className={s.panelTop}><span className={s.panelTitle}>YOUR PROJECTS</span><button className={s.iconButton} aria-label="Create project" onClick={()=>setCreate(true)}>＋ New</button></div>
          {projects.map(p=><button key={p.id} className={`${s.listButton} ${p.id===id?s.selected:""}`} onClick={()=>{setId(p.id);setKnowledge(false);}}>{p.title}</button>)}
          {!projects.length && <p className={s.hint}>Create your first project to save its files and responses.</p>}
        </aside>
        <div className={s.body}>
          {!id?<div className={s.centered}><span className={s.welcomeIcon}>▦</span><h2>Keep your ideas together.</h2><p>Give MioAgent context once: instructions, files and saved memories stay attached to your project.</p><button className={s.primary} onClick={()=>setCreate(true)}>Create project</button></div>:<>
            <div className={s.heading}><div className={s.pillRow} style={{justifyContent:"space-between"}}><div><h2>{detail?.title||"Opening project…"}</h2><p>{detail?.instructions?detail.instructions.slice(0,130):"A private space for your ongoing research and files"}</p></div><button className={s.secondary} onClick={()=>setKnowledge(true)}>▤ Files & instructions</button></div></div>
            <div className={s.scroll}><div className={s.narrow}>
              {!items.length && <div className={s.centered}><span className={s.welcomeIcon}>✳</span><h2>Start a project discussion</h2><p>Ask questions using this project's instructions and linked documents.</p></div>}
              {items.map(item=>{const run=runs[item.id];return <div key={item.id} className={s.bubbleRow}><div className={s.userBubble}>{item.prompt}</div><div className={s.assistantBubble}><span className={s.role}>✳ MioAgent <span className={`${s.state} ${item.state==="needs_review"?s.warning:item.state==="failed"?s.failed:""}`}>{item.state.replaceAll("_"," ")}</span></span>{run?.result?<RichText text={run.result}/>:<div className={s.loading}>{done(item.state)?run?.error??"Could not load result":"Running on Ubuntu server…"}</div>}{run?.sources&&run.sources.length>0&&<div>{run.sources.map(src=><a className={s.source} key={src.ref} href={src.url} target="_blank" rel="noopener noreferrer">[{src.ref}] {src.title}</a>)}</div>}{run?.result&&<div className={s.answerNote}><span>{run.model||"Local model"}</span><a className={s.textLink} href={`/api/proxy/work/runs/${item.id}/artifact`} target="_blank" rel="noopener noreferrer">Open Markdown ↗</a></div>}</div></div>;})}
              <div ref={bottom}/>{error&&<p className={s.error} role="alert">{error}</p>}
            </div></div>
            <div className={s.composerArea}><div className={s.composer}><textarea aria-label="Message project" value={prompt} onChange={e=>setPrompt(e.target.value)} rows={2} maxLength={6000} disabled={busy} placeholder="Message this project…" onKeyDown={e=>{if(e.key==="Enter"&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();void send();}}}/><div className={s.composeBottom}><div className={s.pillRow}><input hidden type="file" multiple ref={upload} onChange={e=>void attach(e.target.files)}/><button className={s.iconButton} aria-label="Attach project files" disabled={busy} onClick={()=>upload.current?.click()}>＋ Attach files</button><span className={s.hint}>Saved with project</span></div><button className={s.send} disabled={busy||prompt.trim().length<4} onClick={()=>void send()}>Send ↑</button></div></div><p className={s.note}>Project instructions, approved memories and files are used. Automatic cross-turn chat reasoning is not yet implemented.</p></div>
          </>}
        </div>
      </div>
      {knowledge&&id&&<aside className={s.pane} aria-label="Project knowledge"><div className={s.paneHeader}><h3>Project knowledge</h3><button className={s.iconButton} onClick={()=>setKnowledge(false)} aria-label="Close project knowledge">✕</button></div><strong>Instructions</strong><div className={s.notice}><div className={s.instructions}>{detail?.instructions||"No project instructions saved yet."}</div><p className={s.hint}>Editable instructions and revision history are planned; existing instructions are read-only.</p></div><hr className={s.sep}/><div className={s.paneHeader}><strong>Files</strong><button className={s.secondary} onClick={()=>upload.current?.click()} disabled={busy}>＋ Add</button></div>{detail?.assets.map(a=><div className={s.listItem} key={a.id}><strong>{a.name}</strong>{a.kind}</div>)}{!detail?.assets.length&&<p className={s.hint}>No files linked yet.</p>}<hr className={s.sep}/><strong>Approved memory</strong><p className={s.hint}>Only memories you explicitly save are retained.</p><label className={s.field}>Add a memory<textarea value={memory} onChange={e=>setMemory(e.target.value)} maxLength={1500} placeholder="A decision or fact to remember" /></label><button className={s.secondary} disabled={busy||memory.trim().length<3} onClick={()=>void remember()}>Save memory</button>{detail?.memories.map(m=><div className={s.listItem} key={m.id}><p>{m.content}</p><button className={s.iconButton} onClick={()=>void removeMemory(m.id)}>Remove</button></div>)}</aside>}
      {create&&<div className={s.pane} role="dialog" aria-label="Create project"><div className={s.paneHeader}><h3>New project</h3><button className={s.iconButton} onClick={()=>setCreate(false)}>✕</button></div><p className={s.notice}>Projects hold instructions, files, saved memories and their own response history. Delegated computer work belongs in Work.</p><label className={s.field}>Name<input autoFocus value={name} onChange={e=>setName(e.target.value)} maxLength={120} placeholder="e.g. Robotics literature review" /></label><label className={s.field}>Instructions<textarea value={instructions} onChange={e=>setInstructions(e.target.value)} maxLength={6000} placeholder="What MioAgent should remember about this project" /></label><button className={s.primary} disabled={busy||name.trim().length<3} onClick={()=>void newProject()}>Create project</button>{error&&<p className={s.error}>{error}</p>}</div>}
    </div>
  </UIShell>;
}
