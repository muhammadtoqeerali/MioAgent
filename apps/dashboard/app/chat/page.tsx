"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import UIShell from "../_mio/ui-shell";
import RichText from "../_mio/rich-text";
import { mioApi, postJson } from "../_mio/api";
import s from "../_mio/experience.module.css";

type Conversation = { id:string; title:string; updated_at:string };
type Message = { id:string;role:string;content:string;task_id:string|null };
type Task = {status:string;progress:number;error:string|null;result:{answer?:string;model?:string}|null};
type Model = {configured:boolean;local_reachable:boolean;local_model:string|null};
type Image = {id:string;prompt:string;state:string;error?:string};

export default function Chat() {
  const [history,setHistory] = useState<Conversation[]>([]);
  const [showArchived,setShowArchived] = useState(false);
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
  const thread = useRef<HTMLElement>(null);
  const followLatest = useRef(true);
  const trackScroll = () => {
    const node = thread.current;
    if (node) followLatest.current = node.scrollHeight - node.scrollTop - node.clientHeight < 120;
  };

  const reload = useCallback(async ()=>{
    const [list,status] = await Promise.all([
      mioApi<{conversations:Conversation[]}>(`assistant/conversations?archived=${showArchived}`),
      mioApi<Model>("assistant/status"),
    ]);
    setHistory(list.conversations);setModel(status);
  },[showArchived]);
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

  async function send(){
    const content=prompt.trim();if(!content || sending || content.length<3)return;
    setError("");setSending(true);
    try{
      // Chat automatically recognizes image intent; image-only mode stays optional.
      const destination = imageMode ? "image" :
        (await mioApi<{mode:string}>("studio/intent", postJson({prompt:content}))).mode;
      if(destination === "image"){
        const result=await fetch("/api/studio", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({prompt:content,mode:"image",attachments:[]})});
        const data=await result.json();
        if(!result.ok || typeof data.image_job!=="string")throw new Error(data.detail??"Image request failed");
        setImage({id:data.image_job,prompt:content,state:"queued"});setPrompt("");
        return;
      }
      const response=await mioApi<{conversation_id:string;task_id:string}>("assistant/ask",postJson({prompt:content,conversation_id:selected}));
      setSelected(response.conversation_id);setPending(response.task_id);setCurrent(null);setPrompt("");
      await load(response.conversation_id);await reload();
    }catch(e){setError(e instanceof Error?e.message:"Unable to send");setSending(false);}
  }
  async function chatAction(action:"archive"|"restore"|"delete"){
    if(!selected||sending)return;
    if(action==="delete" && !window.confirm("Permanently delete this chat, its messages and linked chat tasks from MioAgent's backend? This cannot be undone."))return;
    try{
      await mioApi(`assistant/conversations/${selected}${action==="delete"?"":`/${action}`}`, {method:action==="delete"?"DELETE":"POST"});
      setSelected(null);setMessages([]);setCurrent(null);setError("");await reload();
    }catch(e){setError(e instanceof Error?e.message:"Could not update chat");}
  }
  const start=()=>{if(sending)return;followLatest.current=true;setSelected(null);setMessages([]);setCurrent(null);setPending(null);setImage(null);setPrompt("");setError("");};
  return <UIShell section="chat" title="Chat" subtitle="Everyday conversation · Your local model" sidebarContent={<>
    <button className={s.secondary} onClick={start}>＋ New chat</button>
    <button className={s.iconButton} onClick={()=>{setSelected(null);setMessages([]);setShowArchived(v=>!v);}}>{showArchived?"← Active chats":"Archived chats"}</button>
    {selected&&<div className={s.pillRow}>
      <button className={s.iconButton} disabled={sending} onClick={()=>void chatAction(showArchived?"restore":"archive")}>{showArchived?"Restore":"Archive"}</button>
      <button className={s.iconButton} disabled={sending} onClick={()=>void chatAction("delete")}>Delete permanently</button>
    </div>}
    <div className={s.sideCaption}>{showArchived?"ARCHIVED CHATS":"RECENT CHATS"}</div>
    {history.map(c=><button key={c.id} className={`${s.questionBtn} ${selected===c.id?s.questionActive:""}`} onClick={()=>{if(sending)return;followLatest.current=true;setSelected(c.id);setCurrent(null);setImage(null);}} title={c.title}>{c.title}</button>)}
    {!history.length && <p className={s.hint}>New conversations appear here automatically.</p>}
  </>}>
    <section className={s.stage} ref={thread} onScroll={trackScroll} aria-label="Chat conversation">
      <div className={s.narrow}>
        {!messages.length && !image && <div className={s.centered}><span className={s.welcomeIcon}>✳</span><h2>How can MioAgent help?</h2><p>Ask a question, write together, or explore an idea. Create a Project when you want persistent instructions and shared files.</p><div className={s.promptButtons}><button onClick={()=>setPrompt("Help me outline a research paper on humanoid robotics.")}>Plan an idea</button><button onClick={()=>setPrompt("Explain transformer models in simple terms.")}>Learn a topic</button><button onClick={()=>setImageMode(true)}>Create an image</button></div></div>}
        {messages.map(m=><div key={m.id} className={s.bubbleRow}>{m.role==="user"?<div className={s.userBubble}>{m.content}</div>:<article className={s.assistantBubble}><span className={s.role}>✳ MioAgent</span><RichText text={m.content}/></article>}</div>)}
        {pending && <article className={s.assistantBubble} role="status"><span className={s.role}>✳ MioAgent is responding</span><div className={s.loading}>{current?`${current.status} · ${current.progress}%`:"Queued on local server…"}</div></article>}
        {current && ["failed","canceled"].includes(current.status) && <div className={s.error}>{current.error || "Local task did not complete"}</div>}
        {image && <article className={s.assistantBubble}><span className={s.role}>✳ Image creation</span><p>{image.prompt}</p>{image.state==="ready"?<a href={`/api/studio-image/${image.id}`} target="_blank" rel="noopener noreferrer"><img className={s.image} src={`/api/studio-image/${image.id}`} alt={image.prompt}/><span className={s.textLink}>Open full PNG ↗</span></a>:<div className={s.notice}>{image.state==="failed"?image.error:"Rendering on local ComfyUI…"}</div>}<p className={s.hint}>Generated images remain in the private Studio store; chat-history linking is a future update.</p></article>}
        {error && <p className={s.error} role="alert">{error}</p>}

      </div>
    </section>
    <div className={s.composerArea}><div className={s.composer}>
      <textarea aria-label="Message MioAgent" value={prompt} onChange={e=>setPrompt(e.target.value)} rows={2} maxLength={imageMode?1200:12000} disabled={sending||(!imageMode&&!model?.configured)} placeholder={imageMode?"Describe the image you want to create…":"Message MioAgent…"} onKeyDown={e=>{if(e.key==="Enter"&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();void send();}}}/>
      <div className={s.composeBottom}><div className={s.pillRow}><button className={s.iconButton} onClick={()=>setImageMode(v=>!v)} disabled={sending} aria-pressed={imageMode} aria-label={imageMode?"Switch to chat":"Create an image"}>{imageMode?"← Chat":"▧ Image"}</button><span className={s.hint}>{imageMode?"Uses local ComfyUI":"Enter to send · Shift+Enter for new line"}</span></div><button className={s.send} disabled={!prompt.trim()||sending||(!imageMode&&!model?.configured)} onClick={()=>void send()}>{sending?"Working…":"Send ↑"}</button></div>
    </div><div className={s.note}>Local AI can make mistakes. Online research, connected project files and delegated execution live in Projects / Work.</div></div>
  </UIShell>;
}
