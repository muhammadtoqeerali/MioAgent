"use client";

import { useEffect, useRef, useState } from "react";
import styles from "./image-lab.module.css";

type Backend = {id: "sd15" | "flux2"; name: string; available: boolean; generation: boolean; editing: boolean};
type Capabilities = {default: string; backends: Backend[]};
type Job = {id: string; state: string; backend: string; operation: string; fallback_used: boolean; error?: string | null};
const MAX_BYTES = 8 * 1024 * 1024;

async function api<T>(path: string, payload?: object): Promise<T> {
  const response = await fetch(`/api/proxy/studio/${path}`, {
    method: payload ? "POST" : "GET", cache: "no-store",
    headers: payload ? {"Content-Type": "application/json"} : undefined,
    body: payload ? JSON.stringify(payload) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Server responded ${response.status}`);
  return data as T;
}

async function encode(file: File): Promise<string> {
  if (file.size === 0 || file.size > MAX_BYTES) throw new Error("Image size must be 1 byte to 8 MiB");
  const bytes = new Uint8Array(await file.arrayBuffer());
  const chunks: string[] = [];
  for (let i = 0; i < bytes.length; i += 8192) chunks.push(String.fromCharCode(...bytes.subarray(i, i + 8192)));
  return btoa(chunks.join(""));
}

export default function ImageLab() {
  const [cap, setCap] = useState<Capabilities | null>(null);
  const [backend, setBackend] = useState<"sd15" | "flux2">("flux2");
  const [mode, setMode] = useState<"generate" | "edit">("generate");
  const [prompt, setPrompt] = useState("");
  const [attachment, setAttachment] = useState<string | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [selectedName, setSelectedName] = useState("");
  const [loading, setLoading] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const upload = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void api<Capabilities>("image-lab/capabilities").then(setCap)
      .catch((e: Error) => setError(e.message));
  }, []);
  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.state)) return;
    let alive = true;
    const poll = async () => {
      try {
        const info = await api<Job>(`image-lab/jobs/${job.id}`);
        if (alive) setJob(info);
      } catch (e) { if (alive) setError(e instanceof Error ? e.message : "Image status failed"); }
    };
    void poll();
    const timer = setInterval(() => void poll(), 2500);
    return () => {alive = false; clearInterval(timer);};
  }, [job?.id, job?.state]);
  useEffect(() => () => {if (preview) URL.revokeObjectURL(preview);}, [preview]);

  async function attach(file?: File) {
    if (!file || loading) return;
    setError("");
    if (!/\.(png|jpe?g)$/i.test(file.name)) {setError("Editing currently supports PNG and JPEG images");return;}
    setLoading(true);
    try {
      const base64 = await encode(file);
      const uploaded = await api<{id: string}>("attachments", {filename: file.name, base64});
      setAttachment(uploaded.id);
      setSelectedName(file.name);
      setPreview(URL.createObjectURL(file));
      setMode("edit"); setBackend("flux2");
    } catch (e) { setError(e instanceof Error ? e.message : "Attachment failed"); }
    finally {setLoading(false);if (upload.current) upload.current.value = "";}
  }

  async function run() {
    if (loading || !prompt.trim() || (mode === "edit" && !attachment)) return;
    setLoading(true);setError("");setJob(null);
    try {
      const result = await api<Job>("image-lab/jobs", {prompt: prompt.trim(), backend,
        attachment: mode === "edit" ? attachment : null, fallback_to_sd15: false});
      setJob(result);
    } catch (e) {setError(e instanceof Error ? e.message : "Image request failed");}
    finally {setLoading(false);}
  }

  const busy = loading || (job !== null && ["queued", "running"].includes(job.state));
  const fileUrl = job?.state === "ready" ? `/api/studio-image/${job.id}` : null;

  return <main className={styles.main}>
    <nav className={styles.nav}><a href="/chat">← Chat</a><a href="/studio">Studio</a><a href="/work">Work</a></nav>
    <h1>MioAgent Image Lab</h1>
    <p className={styles.intro}>FLUX.2 Klein is selected automatically for local image creation and editing. SD1.5 remains installed only for rollback.</p>
    <section className={styles.panel} aria-label="Image editor controls">
      <div className={styles.modes}><button type="button" aria-pressed={mode === "generate"} onClick={() => setMode("generate")} disabled={busy}>Create image</button>
      <button type="button" aria-pressed={mode === "edit"} onClick={() => {setMode("edit");setBackend("flux2");}} disabled={busy}>Edit uploaded image</button></div>
      <p className={styles.info}>Model: FLUX.2 Klein 4B · automatically selected{cap?.backends.find(x=>x.id==="flux2")?.available ? " · Ready" : " · Unavailable"}</p>
      {mode === "edit" && <div className={styles.upload} onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {e.preventDefault();void attach(e.dataTransfer.files[0]);}}>
        <input ref={upload} type="file" accept="image/png,image/jpeg" hidden onChange={(e) => void attach(e.target.files?.[0])}/>
        <button type="button" disabled={busy} onClick={() => upload.current?.click()}>Choose reference photo (PNG / JPG)</button>
        <p>Or drag and drop a PNG/JPEG, 8 MiB maximum, 256–2048 pixels, up to 3 megapixels.</p>
        {preview && <><img className={styles.reference} src={preview} alt={`Uploaded reference: ${selectedName}`}/><p>{selectedName}</p></>}
      </div>}
      <label className={styles.label} htmlFor="instruction">{mode === "edit" ? "Describe what to change and what to preserve" : "Describe the image to generate"}</label>
      <textarea id="instruction" maxLength={1200} rows={5} value={prompt} onChange={(e) => setPrompt(e.target.value)}
        placeholder={mode === "edit" ? "Change only the jacket to blue. Keep the face, pose and background unchanged." : "Photorealistic full-body portrait, natural anatomy, soft daylight…"}/>
      {mode === "edit" && backend === "sd15" && <p className={styles.error}>SD1.5 does not edit images. Select FLUX.2 Klein.</p>}
      {error && <p role="alert" className={styles.error}>{error}</p>}
      <button className={styles.submit} disabled={busy || prompt.trim().length < 4 || (mode === "edit" && (!attachment || backend === "sd15"))}
        onClick={() => void run()}>{busy ? "Working on the local GPU…" : mode === "edit" ? "Edit reference image" : "Generate image"}</button>
    </section>
    {job && <section className={styles.panel} aria-live="polite"><h2>Result</h2>
      <p>Job: {job.state} · Model: {job.backend === "flux2" ? "FLUX.2 Klein 4B" : "SD1.5"} · {job.operation === "edit" ? "Reference edit" : "Generation"}
      {job.fallback_used ? " · Used SD1.5 fallback" : ""}</p>
      {job.error && <p className={styles.error}>{job.error}</p>}
      {fileUrl && <><a href={fileUrl} target="_blank" rel="noreferrer"><img className={styles.result} src={fileUrl} alt="Generated image result"/></a>
        <a className={styles.download} href={`${fileUrl}?download=1`} download={`mioagent-${job.id}.png`}>↓ Download PNG</a></>}
    </section>}
    <p className={styles.footnote}>Private local execution. Images are stored in MioAgent’s existing owner-private image store; reference uploads are also copied to local ComfyUI input storage for editing. No cloud image service is used. Image edits may change unintended details, so inspect results.</p>
  </main>;
}
