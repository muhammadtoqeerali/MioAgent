"use client";

import { useEffect, useRef, useState } from "react";
import styles from "./studio.module.css";
import { OmniImageView, imageIntent, sendImage } from "../_mio/omni-image";

type Source = { ref: string; title: string; url: string; snippet: string };
type Attachment = { id: string; name: string; kind: string; bytes: number; sha256: string };
type ResponseData = { answer: string; model: string; mode: string; sources: Source[]; attachments: {ref: string;name:string}[]; source_scope: string };
type Turn = { prompt: string; result: ResponseData | null; error: string | null; image?: string; omni?: string };
type Capabilities = { release: string; installed_models: string[]; image_generation_ready: boolean; image_generation_backend: string; fleet_active: boolean };
const MAX_FILE = 8 * 1024 * 1024;

async function proxy<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/proxy/${path}`, { cache: "no-store", ...init });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

async function encodeFile(file: File): Promise<string> {
  if (file.size > MAX_FILE || file.size === 0) throw new Error(`${file.name}: 8 MiB file limit`);
  const data = new Uint8Array(await file.arrayBuffer());
  const chunks: string[] = [];
  for (let i = 0; i < data.length; i += 8192) {
    chunks.push(String.fromCharCode(...data.subarray(i, i + 8192)));
  }
  return btoa(chunks.join(""));
}

export default function Studio() {
  const [cap, setCap] = useState<Capabilities | null>(null);
  const [prompt, setPrompt] = useState("");
  const [files, setFiles] = useState<Attachment[]>([]);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [imageJob, setImageJob] = useState<string | null>(null);
  const [studioImageChat,setStudioImageChat] = useState<string|null>(null);
  const upload = useRef<HTMLInputElement>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void proxy<Capabilities>("studio/capabilities").then(setCap)
      .catch((e: Error) => setError(e.message));
  }, []);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [turns, busy]);
  useEffect(() => {
    if (!imageJob) return;
    let active = true;
    const poll = async () => {
      try {
        const info = await proxy<{ id: string; state: string; error?: string }>(`studio/images/${imageJob}`);
        if (!active) return;
        if (info.state === "ready" || info.state === "failed") {
          setTurns((prev) => {
            const next = [...prev];
            const last = next.length - 1;
            if (last >= 0) next[last] = {
              ...next[last], error: info.state === "failed" ? (info.error ?? "Image failed") : null,
              image: info.state === "ready" ? `/api/studio-image/${imageJob}` : undefined,
              result: info.state === "ready" ? { answer: "Generated with your local ComfyUI checkpoint.", model: "ComfyUI", mode: "image", sources: [], attachments: [], source_scope: "Local image" } : null,
            };
            return next;
          });
          setImageJob(null); setBusy(false);
        }
      } catch (e) {
        if (active) { setError(e instanceof Error ? e.message : "Image status unavailable"); setBusy(false); setImageJob(null); }
      }
    };
    void poll();
    const timer = setInterval(() => void poll(), 2500);
    return () => { active = false; clearInterval(timer); };
  }, [imageJob]);

  async function attach(input: FileList | null) {
    if (!input?.length || busy) return;
    setBusy(true); setError("");
    try {
      const selected = Array.from(input);
      if (selected.length + files.length > 6) throw new Error("Maximum six attachments per question");
      const added: Attachment[] = [];
      for (const file of selected) {
        const base64 = await encodeFile(file);
        const entry = await proxy<Attachment>("studio/attachments", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ filename: file.name, base64 }),
        });
        added.push(entry);
      }
      setFiles((prev) => [...prev, ...added]);
    } catch (e) { setError(e instanceof Error ? e.message : "Upload failed"); }
    finally { if (upload.current) upload.current.value = ""; setBusy(false); }
  }

  async function send() {
    const question = prompt.trim();
    if (!question || busy) return;
    setBusy(true); setError("");
    let queuedImage = false;
    setTurns((prev) => [...prev, { prompt: question, result: null, error: null }]);
    setPrompt("");
    try {
      const reference=files.find(f=>f.kind==="image");
      const directive=await imageIntent(question,"chat",studioImageChat,reference?.id??null);
      if(directive.image){
        if(reference && files.length!==1)throw new Error("Use exactly one reference image when editing.");
        const created=await sendImage(question,"chat",studioImageChat,reference?.id??null,
          reference?"edit":"auto");
        setStudioImageChat(created.conversation_id);
        setTurns(prev=>{const next=[...prev];next[next.length-1]={prompt:question,result:{
          answer:"",model:created.model,mode:"image",sources:[],attachments:[],source_scope:"Persistent FLUX.2 image"},
          error:null,omni:created.turn_id};return next;});
        setFiles([]);return;
      }
      const response = await fetch("/api/studio", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: question, mode: "auto", attachments: files.map((f) => f.id) }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail ?? `Assistant failed (${response.status})`);
      if (result.operation === "image" && typeof result.image_job === "string") {
        queuedImage = true;
        setFiles([]);
        setImageJob(result.image_job);
        return;
      }
      setTurns((prev) => { const next = [...prev]; next[next.length - 1] = { prompt: question, result, error: null }; return next; });
      setFiles([]);
    } catch (e) {
      const reason = e instanceof Error ? e.message : "Model request failed";
      setTurns((prev) => { const next = [...prev]; next[next.length - 1] = { prompt: question, result: null, error: reason }; return next; });
    } finally { if (!queuedImage) setBusy(false); }
  }

  return <div className={styles.shell}>
    <aside className={styles.side}>
      <div className={styles.logo}>✦ MioAgent <span>STUDIO v0.4I</span></div>
      <a href="/" className={styles.link}>← Dashboard</a>
      <a href="/studio/image-lab" className={styles.link}>✦ Image Lab · FLUX.2 editing</a>
      <a href="/work" className={styles.link}>◈ Persistent Projects &amp; Work</a>
      <a href="/intelligence" className={styles.link}>◇ Engineering &amp; models</a>
      <a href="/assistant" className={styles.link}>◇ Conversation history</a>
      <div className={styles.subheading}>TOOLS</div>
      <div className={styles.capability}>⌕ Live research <small>External search snippets + sources</small></div>
      <div className={styles.capability}>▤ Files and images <small>Private workstation attachment store</small></div>
      <div className={styles.capability}>✦ Local image creator <small>{cap?.image_generation_ready ? "ComfyUI ready" : "ComfyUI not configured"}</small></div>
      <div className={styles.bottom}>Models: {cap?.installed_models.join(", ") || "Checking Ollama…"}
        <small>Active fleet: {cap?.fleet_active ? "Yes" : "No"}</small>
      </div>
    </aside>
    <main className={styles.main}>
      <header className={styles.head}><div><strong>MioAgent Studio</strong><small>One chat · Automatic web, files and image tools</small></div><span className={styles.local}>LOCAL MODELS</span></header>
      <section className={styles.thread}>
        {!turns.length && <div className={styles.welcome}>
          <span className={styles.spark}>✦</span><h1>What can I help you make?</h1>
          <p>Ask about current information, attach documents or images, or create artwork with a configured local generator. Evidence and tool availability are shown with every answer.</p>
          <div className={styles.tiles}>
            <button onClick={() => {setPrompt("Research recent developments in ");}}>⌕ Research with sources</button>
            <button onClick={() => {upload.current?.click();}}>▤ Analyze a document</button>
            <button onClick={() => {setPrompt("Create an illustration of ");}}>✦ Generate an image</button>
          </div>
        </div>}
        {turns.map((turn, i) => <div key={i} className={styles.turn}>
          <div className={styles.question}><b>You</b><p>{turn.prompt}</p></div>
          <div className={styles.answer}><b>✦ MioAgent</b>
            {turn.error ? <p className={styles.error}>{turn.error}</p> : turn.result ? <>
              <div className={styles.response}>{turn.result.answer}</div>
              {turn.omni && <OmniImageView id={turn.omni} onEdit={()=>setPrompt("Change this image: ")}/>}
              {turn.image && <><a href={turn.image} target="_blank" rel="noopener noreferrer"><img src={turn.image} alt={turn.prompt} className={styles.generated} /></a><a href={`${turn.image}?download=1`} download={`mioagent-${turn.image.split("/").pop()}.png`} className={styles.model}>↓ Download PNG</a></>}
              {turn.result.sources.length > 0 && <div className={styles.sources}><h3>Retrieved sources (search snippets)</h3>
                {turn.result.sources.map((s) => <div key={s.ref} className={styles.source}><span>[{s.ref}]</span> <a target="_blank" rel="noopener noreferrer" href={s.url}>{s.title}</a><p>{s.snippet}</p></div>)}
              </div>}
              <small className={styles.model}>Model: {turn.result.model} · {turn.result.source_scope}</small>
            </> : <p className={styles.thinking}>{imageJob ? "Rendering on local image backend…" : "Working…"}</p>}
          </div>
        </div>)}
        <div ref={bottom}/>
      </section>
      <div className={styles.compose}>
        {error && <div role="alert" className={styles.error}>{error}</div>}
        {files.length > 0 && <div className={styles.files}>{files.map((f) => <span key={f.id}>{f.kind === "image" ? "▧" : "▤"} {f.name} <button aria-label={`Remove ${f.name}`} onClick={() => setFiles((s) => s.filter((x) => x.id !== f.id))}>×</button></span>)}</div>}
        <div className={styles.entry}>
          <input type="file" ref={upload} hidden multiple onChange={(e) => void attach(e.target.files)}/>
          <button title="Add files" aria-label="Add files" disabled={busy} onClick={() => upload.current?.click()}>＋</button>
          <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} maxLength={6000} disabled={busy}
            placeholder="Ask anything — research the web, generate an image, or attach a file…"
            onKeyDown={(e) => {if(e.key === "Enter" && (e.ctrlKey || e.metaKey)){e.preventDefault();void send();}}}/>
          <button className={styles.send} disabled={!prompt.trim() || busy} onClick={() => void send()}>{busy ? "…" : "↑"}</button>
        </div>
        <small className={styles.disclaimer}>Ctrl+Enter to send · Automatic tool selection · Files max 8 MiB · Web queries go to public search providers · Images require local ComfyUI</small>
      </div>
    </main>
  </div>;
}
