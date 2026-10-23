"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import UIShell from "../_mio/ui-shell";
import RichText from "../_mio/rich-text";
import { mioApi, postJson } from "../_mio/api";
import s from "../_mio/experience.module.css";
import { imageIntent, sendImage, OmniImageView } from "../_mio/omni-image";

type Conversation = { id:string; title:string; updated_at:string; archived?:boolean };
type Message = { id:string;role:string;content:string;task_id:string|null };
type Task = {status:string;progress:number;error:string|null;result:{answer?:string;model?:string}|null};
type Model = {configured:boolean;local_reachable:boolean;local_model:string|null};
type Image = {id:string;prompt:string;state:string;error?:string};
type Attachment = {id:string;name:string;kind:string;bytes:number;sha256:string;preview?:string};
type FileTurn = {prompt:string;files:string[];answer:string;model:string};
const MAX_FILE = 8 * 1024 * 1024;

async function encodeFile(file: File): Promise<string> {
  if (!file.size || file.size > MAX_FILE) throw new Error(`${file.name}: maximum 8 MiB per file`);
  const bytes = new Uint8Array(await file.arrayBuffer());
  const parts: string[] = [];
  for (let i = 0; i < bytes.length; i += 8192) {
    parts.push(String.fromCharCode(...bytes.subarray(i, i + 8192)));
  }
  return btoa(parts.join(""));
}

export default function Chat() {
  const [history,setHistory] = useState<Conversation[]>([]);
  const [selected,setSelected] = useState<string|null>(null);
  const [messages,setMessages] = useState<Message[]>([]);
  const [prompt,setPrompt] = useState("");
  const [model,setModel] = useState<Model|null>(null);
  const [pending,setPending] = useState<string|null>(null);
  const [current,setCurrent] = useState<Task|null>(null);
  const [sending,setSending] = useState(false);
  const [error,setError] = useState("");
  const [imageMode,setImageMode] = useState(false);
  const [image,setImage] = useState<Image|null>(null);
  const [files,setFiles] = useState<Attachment[]>([]);
  const [fileTurns,setFileTurns] = useState<FileTurn[]>([]);
  const picker = useRef<HTMLInputElement>(null);
  const thread = useRef<HTMLElement>(null);
  const followLatest = useRef(true);
  const trackScroll = () => {
    const node = thread.current;
    if (node) followLatest.current = node.scrollHeight - node.scrollTop - node.clientHeight < 120;
  };

  const reload = useCallback(async ()=>{
    const [list,status] = await Promise.all([
      mioApi<{conversations:Conversation[]}>("omni/conversations"),
      mioApi<Model>("assistant/status"),
    ]);
    setHistory(list.conversations);setModel(status);
  },[]);
  const load = useCallback(async (id:string)=>{
    const data=await mioApi<{messages:Message[]}>(`assistant/conversations/${id}`);
    setMessages(data.messages);
  },[]);
  useEffect(()=>{void reload().catch((e:Error)=>setError(e.message));},[reload]);
  useEffect(()=>{if(selected) void load(selected).catch((e:Error)=>setError(e.message));},[selected,load]);
  useEffect(()=>{
    const node=thread.current;
    if(node && followLatest.current) node.scrollTop=node.scrollHeight;
  },[messages,current,image]);
  useEffect(()=>{
    if(!pending) return;
    let alive=true;
    const tick=async()=>{
      try{
        const task=await mioApi<Task>(`tasks/${pending}`);
        if(!alive)return;
        setCurrent(task);
        if(["completed","failed","canceled"].includes(task.status)){
          setPending(null);setSending(false);
          if(selected) await load(selected);
          void reload();
        }
      }catch(e){if(alive)setError(e instanceof Error?e.message:"Task status unavailable");}
    };
    void tick();const timer=setInterval(()=>void tick(),2400);
    return ()=>{alive=false;clearInterval(timer);};
  },[pending,selected,load,reload]);
  useEffect(()=>{
    if(!image || !["queued","running"].includes(image.state))return;
    let alive=true;
    const tick=async()=>{
      try{
        const response=await mioApi<{state:string;error?:string}>(`studio/images/${image.id}`);
        if(alive) {setImage(p=>p?{...p,state:response.state,error:response.error}:null);if(["failed","ready"].includes(response.state))setSending(false);}
      }catch(e){if(alive){setImage(p=>p?{...p,state:"failed",error:e instanceof Error?e.message:"Image status unavailable"}:null);setSending(false);}}
    };
    void tick();const timer=setInterval(()=>void tick(),2600);
    return ()=>{alive=false;clearInterval(timer);};
  },[image]);

  async function attach(input: FileList | null) {
    if (!input?.length || sending) return;
    const selectedFiles = Array.from(input);
    if (files.length + selectedFiles.length > 6) {
      setError("Maximum six attachments per question");
      return;
    }
    setSending(true); setError("");
    const uploaded: Attachment[] = [];
    try {
      for (const file of selectedFiles) {
        const base64 = await encodeFile(file);
        const item = await mioApi<Attachment>("studio/attachments", postJson({filename:file.name,base64}));
        uploaded.push({...item, preview:item.kind === "image" ? URL.createObjectURL(file) : undefined});
      }
      setFiles(prev => [...prev, ...uploaded]);
    } catch(e) {
      uploaded.forEach(item => {if(item.preview) URL.revokeObjectURL(item.preview);});
      setError(e instanceof Error ? e.message : "File upload failed");
    } finally {
      if(picker.current) picker.current.value = "";
      setSending(false);
    }
  }
  function removeFile(id:string) {
    const item = files.find(f => f.id === id);
    if(item?.preview) URL.revokeObjectURL(item.preview);
    setFiles(prev => prev.filter(f => f.id !== id));
  }
  async function send(){
    const content=prompt.trim();if(!content || sending || content.length<2)return;
    setError("");setSending(true);
    let assistantQueued=false;
    try{
      const reference=files.find(f=>f.kind==="image");
      const route=await imageIntent(content,"chat",selected,reference?.id??null);
      if(route.image || imageMode){
        if(reference && files.length>1) throw new Error("Use one reference image per edit; remove other attachments first.");
        const out=await sendImage(content,"chat",selected,reference?.id??null,
          reference?"edit":imageMode?"create":"auto");
        files.forEach(f=>{if(f.preview)URL.revokeObjectURL(f.preview);});
        setFiles([]);setImage(null);setImageMode(false);setPrompt("");
        setSelected(out.conversation_id);await load(out.conversation_id);await reload();
        return;
      }
      if(files.length){
        const response=await fetch("/api/studio",{method:"POST",headers:{"Content-Type":"application/json"},
          body:JSON.stringify({prompt:content,mode:"auto",attachments:files.map(f=>f.id)})});
        const result=await response.json();
        if(!response.ok || result.operation!=="answer" || typeof result.answer!=="string")
          throw new Error(result.detail??"File analysis did not return a response");
        setFileTurns(prev=>[...prev,{prompt:content,files:files.map(f=>f.name),answer:result.answer,model:result.model}]);
        files.forEach(f=>{if(f.preview)URL.revokeObjectURL(f.preview);});
        setFiles([]);setPrompt("");
        return;
      }
      const response=await mioApi<{conversation_id:string;task_id:string}>("assistant/ask",postJson({prompt:content,conversation_id:selected}));
      setSelected(response.conversation_id);setPending(response.task_id);setCurrent(null);setPrompt("");
      assistantQueued=true;
      await load(response.conversation_id);await reload();
    }catch(e){setError(e instanceof Error?e.message:"Unable to send");}
    finally{if(!assistantQueued)setSending(false);}
  }
  async function chatAction(action:"archive"|"restore"|"delete"){
    if(!selected||sending)return;
    if(action==="delete" && !window.confirm("Permanently delete this chat, its messages and linked chat tasks from MioAgent's backend? This cannot be undone."))return;
    try{
      await mioApi(`assistant/conversations/${selected}${action==="delete"?"":`/${action}`}`, {method:action==="delete"?"DELETE":"POST"});
      setSelected(null);setMessages([]);setCurrent(null);setError("");await reload();
    }catch(e){setError(e instanceof Error?e.message:"Could not update chat");}
  }
  const start=()=>{if(sending)return;files.forEach(f=>{if(f.preview)URL.revokeObjectURL(f.preview);});setFiles([]);setFileTurns([]);followLatest.current=true;setSelected(null);setMessages([]);setCurrent(null);setPending(null);setImage(null);setPrompt("");setError("");};
  return <UIShell section="chat" title="Chat" subtitle="Everyday conversation · Your local model" sidebarContent={<>
    <button className={s.secondary} onClick={start}>＋ New chat</button>
    <span className={s.hint}>All conversations remain visible until you delete them.</span>
    {selected&&<div className={s.pillRow}>
      <button className={s.iconButton} disabled={sending} onClick={()=>void chatAction(history.find(c=>c.id===selected)?.archived?"restore":"archive")}>{history.find(c=>c.id===selected)?.archived?"Restore":"Archive"}</button>
      <button className={s.iconButton} disabled={sending} onClick={()=>void chatAction("delete")}>Delete permanently</button>
    </div>}
    <div className={s.sideCaption}>ALL CHATS</div>
    {history.map(c=><button key={c.id} className={`${s.questionBtn} ${selected===c.id?s.questionActive:""}`} onClick={()=>{if(sending)return;files.forEach(f=>{if(f.preview)URL.revokeObjectURL(f.preview);});setFiles([]);setFileTurns([]);followLatest.current=true;setSelected(c.id);setCurrent(null);setImage(null);}} title={c.title}>{c.title}</button>)}
    {!history.length && <p className={s.hint}>New conversations appear here automatically.</p>}
  </>}>
    <section className={s.stage} ref={thread} onScroll={trackScroll} aria-label="Chat conversation">
      <div className={s.narrow}>
        {!messages.length && !image && <div className={s.centered}><span className={s.welcomeIcon}>✳</span><h2>How can MioAgent help?</h2><p>Ask a question, write together, or explore an idea. Create a Project when you want persistent instructions and shared files.</p><div className={s.promptButtons}><button onClick={()=>setPrompt("Help me outline a research paper on humanoid robotics.")}>Plan an idea</button><button onClick={()=>setPrompt("Explain transformer models in simple terms.")}>Learn a topic</button><button onClick={()=>setImageMode(true)}>Create an image</button></div></div>}
        {messages.map(m=><div key={m.id} className={s.bubbleRow}>{m.role==="user"?<div className={s.userBubble}>{m.content}</div>:<article className={s.assistantBubble}><span className={s.role}>✳ MioAgent</span><>{m.content.startsWith("MIO_IMAGE_TURN:") ? <OmniImageView id={m.content.slice("MIO_IMAGE_TURN:".length)} onEdit={()=>setPrompt("Change this image: ")}/> : <RichText text={m.content}/>}</></article>}</div>)}
        {fileTurns.map((turn,i)=><div key={`file-turn-${i}`} className={s.bubbleRow}>
          <div className={s.userBubble}>{turn.prompt}<small className={s.attachmentCaption}>Attached: {turn.files.join(", ")}</small></div>
          <article className={s.assistantBubble}><span className={s.role}>✳ MioAgent · {turn.model}</span><RichText text={turn.answer}/>
            <small className={s.hint}>File-assisted answers in this preview are visible here but not yet saved in Chat history.</small>
          </article>
        </div>)}
        {pending && <article className={s.assistantBubble} role="status"><span className={s.role}>✳ MioAgent is responding</span><div className={s.loading}>{current?`${current.status} · ${current.progress}%`:"Queued on local server…"}</div></article>}
        {current && ["failed","canceled"].includes(current.status) && <div className={s.error}>{current.error || "Local task did not complete"}</div>}
        {image && <article className={s.assistantBubble}><span className={s.role}>✳ Image creation</span><p>{image.prompt}</p>{image.state==="ready"?<><a href={`/api/studio-image/${image.id}`} target="_blank" rel="noopener noreferrer"><img className={s.image} src={`/api/studio-image/${image.id}`} alt={image.prompt}/><span className={s.textLink}>Open full PNG ↗</span></a><a className={s.download} download={`mioagent-${image.id}.png`} href={`/api/studio-image/${image.id}?download=1`}>↓ Download PNG</a></>:<div className={s.notice}>{image.state==="failed"?image.error:"Rendering on local ComfyUI…"}</div>}<p className={s.hint}>Generated images remain in the private Studio store; chat-history linking is a future update.</p></article>}
        {error && <p className={s.error} role="alert">{error}</p>}

      </div>
    </section>
    <div className={s.note}><a href="/studio/image-lab">✦ Image Lab — FLUX.2 creation and reference editing</a></div>
    <div className={s.composerArea}><div className={s.composer}
      onDragOver={e=>{if(e.dataTransfer.types.includes("Files"))e.preventDefault();}}
      onDrop={e=>{if(e.dataTransfer.files.length){e.preventDefault();void attach(e.dataTransfer.files);}}}>
      <input ref={picker} type="file" multiple hidden onChange={e=>void attach(e.target.files)}/>
      {files.length>0&&<div className={s.attachedFiles}>{files.map(f=><div key={f.id} className={s.attachedFile}>
        {f.preview?<img src={f.preview} alt={`Preview of ${f.name}`} className={s.attachmentThumb}/>:<span aria-hidden="true">▤</span>}
        <span className={s.attachmentName} title={f.name}>{f.name}</span>
        <button type="button" aria-label={`Remove ${f.name}`} disabled={sending} onClick={()=>removeFile(f.id)}>×</button>
      </div>)}</div>}
      <textarea aria-label="Message MioAgent" value={prompt} onChange={e=>setPrompt(e.target.value)} rows={2} maxLength={imageMode?1200:12000} disabled={sending||(!imageMode&&!model?.configured&&files.length===0)} placeholder={imageMode?"Describe the image you want to create…":"Message MioAgent…"} onPaste={e=>{if(e.clipboardData.files.length){e.preventDefault();void attach(e.clipboardData.files);}}} onKeyDown={e=>{if(e.key==="Enter"&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();void send();}}}/>
      <div className={s.composeBottom}><div className={s.pillRow}><button type="button" title="Attach images or documents" aria-label="Attach files" className={s.iconButton} disabled={sending} onClick={()=>picker.current?.click()}>＋ Attach</button><button className={s.iconButton} onClick={()=>setImageMode(v=>!v)} disabled={sending} aria-pressed={imageMode} aria-label={imageMode?"Switch to chat":"Create an image"}>{imageMode?"← Chat":"▧ Image"}</button><span className={s.hint}>{imageMode?"Uses local ComfyUI":"Enter to send · Shift+Enter for new line"}</span></div><button className={s.send} disabled={!prompt.trim()||sending||(!imageMode&&!model?.configured&&files.length===0)} onClick={()=>void send()}>{sending?"Working…":"Send ↑"}</button></div>
    </div><div className={s.note}>Attach, drop or paste files (6 per request, 8 MiB each). Image creation and reference editing use FLUX.2 automatically. Non-image file answers in this preview are not yet persisted. Online research and persistent project files remain in Studio / Work.</div></div>
  </UIShell>;
}
