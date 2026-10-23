"use client";

import { useEffect, useRef, useState } from "react";
import { mioApi, postJson } from "./api";
import s from "./omni-image.module.css";

export type Scope = "chat" | "project" | "work";
export type OmniTurn = { id: string; prompt: string; state: string; model: string;
  operation: "edit" | "create"; source_turn?: string | null; error?: string | null };
export type OmniResult = { turn_id: string; conversation_id: string; job_id: string;
  operation: string; model: string };

export async function imageIntent(prompt: string, scope: Scope, scope_id: string | null,
  attachment?: string | null): Promise<{ image: boolean; operation: string }> {
  return mioApi("omni/intent", postJson({prompt, scope, scope_id, attachment:attachment || null}));
}
export async function sendImage(prompt: string, scope: Scope, scope_id: string | null,
  attachment?: string | null, mode: "auto" | "create" | "edit" = "auto"): Promise<OmniResult> {
  return mioApi("omni/images", postJson({prompt, scope, scope_id, attachment:attachment || null, mode}));
}

export function OmniImageView({id, onEdit}: {id: string; onEdit?: (id: string) => void}) {
  const [turn,setTurn] = useState<OmniTurn|null>(null);
  const [error,setError] = useState("");
  useEffect(()=>{
    let live=true;
    let timer: ReturnType<typeof setInterval> | undefined;
    const check=async()=>{
      try {const result=await mioApi<OmniTurn>(`omni/images/${id}`);
        if(live){setTurn(result);if(["ready","failed","interrupted"].includes(result.state)&&timer)clearInterval(timer);}}
      catch(e){if(live){setError(e instanceof Error?e.message:"Image unavailable");
        if(timer)clearInterval(timer);}}
    };
    timer=setInterval(()=>void check(),3000);void check();
    return()=>{live=false;if(timer)clearInterval(timer);};
  },[id]);
  const url=`/api/mio-image/${id}`;
  return <div className={s.imageTurn}>
    {turn?.state === "ready" ? <>
      <a href={url} target="_blank" rel="noopener noreferrer"><img className={s.image} src={url} alt={turn.prompt}/></a>
      <div className={s.actions}>
        <a href={`${url}?download=1`} download={`mioagent-${id}.png`}>↓ Download PNG</a>
        {onEdit&&<button type="button" onClick={()=>onEdit(id)}>✦ Make changes</button>}
        <span>FLUX.2 Klein · {turn.operation === "edit" ? "Edited" : "Created"}</span>
      </div>
    </> : <div className={s.status} role="status">{error || turn?.error ||
      (turn?.state === "failed" ? "Image generation failed" :
        turn?.state === "interrupted" ? "Image job was interrupted" : "Creating image using FLUX.2 Klein…")}</div>}
  </div>;
}

export function OmniImageThread({scope,scopeId,revision=0,onEdit}: {
  scope: "project"|"work";scopeId: string|null;revision?:number;onEdit?: (id:string)=>void;
}) {
  const [turns,setTurns] = useState<OmniTurn[]>([]);
  const [error,setError] = useState("");
  useEffect(()=>{
    if(!scopeId){setTurns([]);return;}
    let active=true;
    const reload=async()=>{
      try {const list=await mioApi<{turns:OmniTurn[]}>(`omni/turns/${scope}/${scopeId}`);
        if(active){setTurns(list.turns);setError("");}}
      catch(e){if(active)setError(e instanceof Error?e.message:"Image thread unavailable");}
    };
    void reload();const timer=setInterval(()=>void reload(),3300);
    return()=>{active=false;clearInterval(timer);};
  },[scope,scopeId,revision]);
  return <div className={s.thread}>{turns.map(item=><article key={item.id} className={s.turn}>
    <p className={s.question}><strong>You</strong> {item.prompt}</p>
    <strong>✦ MioAgent image</strong><OmniImageView id={item.id} onEdit={onEdit}/>
  </article>)}{error&&<div className={s.status} role="alert">{error}</div>}</div>;
}

export function WorkImageComposer({scope,scopeId}: {scope:"work"|"project";scopeId:string}){
  const [prompt,setPrompt]=useState("");const [working,setWorking]=useState(false);
  const [error,setError]=useState("");const [revision,setRevision]=useState(0);
  const [attachment,setAttachment]=useState<string|null>(null);
  const picker=useRef<HTMLInputElement>(null);
  async function attach(files:FileList|null){
    const f=files?.[0];if(!f)return;
    if(f.size===0||f.size>8*1024*1024){setError("Reference image must be 1 byte–8 MiB");return;}
    setWorking(true);setError("");
    try{
      const raw=new Uint8Array(await f.arrayBuffer());const chunks:string[]=[];
      for(let i=0;i<raw.length;i+=8192)chunks.push(String.fromCharCode(...raw.subarray(i,i+8192)));
      const item=await mioApi<{id:string}>("studio/attachments",postJson({filename:f.name,base64:btoa(chunks.join(""))}));
      setAttachment(item.id);
    }catch(e){setError(e instanceof Error?e.message:"Upload failed");}
    finally{setWorking(false);if(picker.current)picker.current.value="";}
  }
  async function send(){
    if(!prompt.trim()||working)return;setWorking(true);setError("");
    try{await sendImage(prompt.trim(),scope,scopeId,attachment,attachment?"edit":"auto");
      setPrompt("");setAttachment(null);setRevision(n=>n+1);}
    catch(e){setError(e instanceof Error?e.message:"Image request failed");}
    finally{setWorking(false);}
  }
  return <div className={s.workPanel}>
    <OmniImageThread scope={scope} scopeId={scopeId} revision={revision}
      onEdit={()=>setPrompt("Change this image: ")}/>
    <div className={s.composer}>
      <textarea aria-label="Message MioAgent image assistant" rows={2} value={prompt} disabled={working}
        placeholder="Create an image, or ask to change the last image…" onChange={e=>setPrompt(e.target.value)}
        onKeyDown={e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();void send();}}}/>
      <div className={s.actions}>
        <input type="file" accept="image/png,image/jpeg" hidden ref={picker} onChange={e=>void attach(e.target.files)}/>
        <button type="button" onClick={()=>picker.current?.click()} disabled={working}>＋ Reference image</button>
        {attachment&&<button type="button" onClick={()=>setAttachment(null)}>Reference attached ×</button>}
        <button type="button" onClick={()=>void send()} disabled={working||!prompt.trim()}>{working?"Working…":"Send ↗"}</button>
      </div>{error&&<div role="alert" className={s.status}>{error}</div>}
    </div>
  </div>;
}
