"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import styles from "./work.module.css";

type Project = { id: string; title: string; instructions: string; created: number };
type Note = { id: string; content: string };
type Asset = { id: string; name: string; kind: string };
type RunSummary = { id: string; prompt: string; state: string; mode: string; model: string | null };
type Detail = Project & { memories: Note[]; assets: Asset[]; runs: RunSummary[] };
type Source = { ref: string; title: string; url: string; snippet: string };
type WorkEvent = { phase: string; detail: string; created: number };
type WorkRun = RunSummary & { result: string | null; sources: Source[]; error: string | null; events: WorkEvent[] };
type Skill = { id: string; title: string; description: string; tools: string[] };
type Overview = { release: string; projects: Project[]; skills: Skill[]; permissions: Record<string, boolean> };

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/proxy/${path}`, { cache: "no-store", ...init });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(typeof data?.detail === "string" ? data.detail : `API error ${response.status}`);
  }
  return response.json() as Promise<T>;
}

async function encode(file: File): Promise<string> {
  if (!file.size || file.size > 8 * 1024 * 1024) throw new Error(`File limit: 8 MiB (${file.name})`);
  const b = new Uint8Array(await file.arrayBuffer());
  let encoded = "";
  for (let i = 0; i < b.length; i += 8192) encoded += String.fromCharCode(...b.subarray(i, i + 8192));
  return btoa(encoded);
}

export default function WorkPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [run, setRun] = useState<WorkRun | null>(null);
  const [title, setTitle] = useState("");
  const [instructions, setInstructions] = useState("");
  const [prompt, setPrompt] = useState("");
  const [memory, setMemory] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [showNew, setShowNew] = useState(false);
  const picker = useRef<HTMLInputElement>(null);

  const reload = useCallback(async () => {
    try {
      const info = await api<Overview>("work/overview");
      setOverview(info);
      setSelected((current) => current ?? info.projects[0]?.id ?? null);
    } catch (e) { setError(e instanceof Error ? e.message : "Workspace unavailable"); }
  }, []);
  const loadProject = useCallback(async (id: string) => {
    try { setDetail(await api<Detail>(`work/projects/${id}`)); }
    catch (e) { setError(e instanceof Error ? e.message : "Cannot open project"); }
  }, []);

  useEffect(() => { void reload(); }, [reload]);
  useEffect(() => {
    if (!selected) { setDetail(null); return; }
    void loadProject(selected);
    const timer = setInterval(() => void loadProject(selected), 3500);
    return () => clearInterval(timer);
  }, [selected, loadProject]);
  useEffect(() => {
    if (!runId) { setRun(null); return; }
    let live = true;
    const poll = async () => {
      try { const next = await api<WorkRun>(`work/runs/${runId}`); if (live) setRun(next); }
      catch (e) { if (live) setError(e instanceof Error ? e.message : "Cannot load run"); }
    };
    void poll();
    const timer = setInterval(() => void poll(), 2200);
    return () => { live = false; clearInterval(timer); };
  }, [runId]);

  async function createProject() {
    if (busy || title.trim().length < 3) return;
    setBusy(true); setError("");
    try {
      const project = await api<Project>("work/projects", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, instructions }) });
      setSelected(project.id); setTitle(""); setInstructions(""); setShowNew(false); setRunId(null);
      await reload();
    } catch (e) { setError(e instanceof Error ? e.message : "Project creation failed"); }
    finally { setBusy(false); }
  }
  async function send() {
    if (!selected || busy || prompt.trim().length < 4) return;
    setBusy(true); setError("");
    try {
      const result = await api<{ id: string }>(`work/projects/${selected}/runs`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt: prompt.trim() }),
      });
      setRunId(result.id); setPrompt(""); await loadProject(selected);
    } catch (e) { setError(e instanceof Error ? e.message : "Task could not start"); }
    finally { setBusy(false); }
  }
  async function saveMemory() {
    if (!selected || busy || memory.trim().length < 3) return;
    setBusy(true); setError("");
    try { await api(`work/projects/${selected}/memory`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: memory.trim(), approved: true }) });
      setMemory(""); await loadProject(selected);
    } catch (e) { setError(e instanceof Error ? e.message : "Could not save memory"); }
    finally { setBusy(false); }
  }
  async function removeMemory(id: string) {
    if (!selected || busy) return;
    setBusy(true);
    try { await api(`work/projects/${selected}/memory/${id}`, { method: "DELETE" }); await loadProject(selected); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not remove memory"); }
    finally { setBusy(false); }
  }
  async function attach(files: FileList | null) {
    if (!selected || !files?.length || busy) return;
    setBusy(true); setError("");
    try {
      for (const file of Array.from(files).slice(0, 6)) {
        const uploaded = await api<{ id: string }>("studio/attachments", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ filename: file.name, base64: await encode(file) }),
        });
        await api(`work/projects/${selected}/files`, { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ attachment_id: uploaded.id }) });
      }
      await loadProject(selected);
    } catch (e) { setError(e instanceof Error ? e.message : "Attachment could not be saved"); }
    finally { if (picker.current) picker.current.value = ""; setBusy(false); }
  }
  function download() {
    if (!run?.result) return;
    const citations = run.sources.map((s) => `- [${s.ref}] ${s.title}: ${s.url}`).join("\n");
    const contents = `# MioAgent Work task\n\n${run.prompt}\n\n${run.result}\n\n## Sources\n${citations}\n`;
    const url = URL.createObjectURL(new Blob([contents], { type: "text/markdown;charset=utf-8" }));
    const link = document.createElement("a"); link.href = url; link.download = `mio-work-${run.id.slice(0, 8)}.md`;
    link.click(); URL.revokeObjectURL(url);
  }

  return <div className={styles.shell}>
    <aside className={styles.sidebar}>
      <div className={styles.brand}>✦ MioAgent <small>WORKSPACE v0.4K</small></div>
      <nav className={styles.navigation}>
        <a href="/studio">← Studio chat &amp; images</a><a href="/intelligence">Engineering console</a><a href="/">System overview</a>
      </nav>
      <div className={styles.row}><b>Projects</b><button onClick={() => setShowNew(!showNew)} aria-label="New project">＋</button></div>
      {overview?.projects.map((p) => <button key={p.id} onClick={() => { setSelected(p.id); setRunId(null); }}
        className={`${styles.projectLink} ${selected === p.id ? styles.active : ""}`}>{p.title}</button>)}
      {!overview?.projects.length && <p className={styles.hint}>Create your first persistent project.</p>}
      {showNew && <div className={styles.newProject}>
        <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} placeholder="Project title" />
        <textarea value={instructions} onChange={(e) => setInstructions(e.target.value)} maxLength={6000} placeholder="Project instructions (optional)" />
        <button disabled={busy || title.trim().length < 3} onClick={() => void createProject()}>Create project</button>
      </div>}
      <div className={styles.sidebarBottom}><span>Local only · Private SQLite</span><small>Project data survives browser reloads. Tool permissions remain enforced by the backend.</small></div>
    </aside>
    <main className={styles.content}>
      <header className={styles.header}><div><strong>{detail?.title ?? "MioAgent Work"}</strong>
        <small>Projects · Evidence · Memory · Deliverables</small></div><span className={styles.chip}>LOCAL WORK</span></header>
      {error && <div role="alert" className={styles.error}>{error} <button onClick={() => setError("")}>Dismiss</button></div>}
      {!selected ? <section className={styles.empty}><h1>Work on projects, not just prompts.</h1><p>Create a project to keep its instructions, files, memory and audited tasks together.</p><button onClick={() => setShowNew(true)}>Create a project →</button></section> : <>
        <div className={styles.workspace}>
          <section className={styles.center}>
            <div className={styles.intro}><h1>{detail?.title ?? "Loading project…"}</h1>
              <p>{detail?.instructions || "Project instructions can be set when creating the project."}</p></div>
            <div className={styles.activity}>
              <h2>Task history</h2>
              {!detail?.runs.length && <p className={styles.hint}>No tasks yet. Ask for research, a literature brief, or an analysis of attached files.</p>}
              {detail?.runs.map((entry) => <button key={entry.id} onClick={() => setRunId(entry.id)}
                className={`${styles.runItem} ${runId === entry.id ? styles.selected : ""}`}>
                <span>{entry.prompt}</span><small>{entry.state.replaceAll("_", " ")}</small>
              </button>)}
            </div>
            {run && <article className={styles.output}>
              <div className={styles.outputHead}><h2>Run evidence</h2><span>{run.state}</span></div>
              <p className={styles.hint}>Mode: {run.mode} · Model: {run.model || "pending"}</p>
              {run.error && <p className={styles.error}>{run.error}</p>}
              {run.result && <><div className={styles.answer}>{run.result}</div><button className={styles.export} onClick={download}>↓ Save Markdown deliverable</button></>}
              {run.sources.length > 0 && <div className={styles.sources}><h3>Retrieved source snippets</h3>
                {run.sources.map((source) => <p key={source.ref}><b>{source.ref}</b> <a href={source.url} target="_blank" rel="noopener noreferrer">{source.title}</a></p>)}
              </div>}
              <div className={styles.events}><h3>Audited actions</h3>{run.events.map((event, i) => <div key={i}><b>{event.phase}</b><span>{event.detail}</span></div>)}</div>
              {run.state === "needs_review" && <p className={styles.warning}>The draft did not pass citation validation. It is available to inspect, but is not verified.</p>}
            </article>}
          </section>
          <aside className={styles.right}>
            <section className={styles.panel}><h2>Project files <span>{detail?.assets.length ?? 0}</span></h2>
              <input ref={picker} type="file" hidden multiple onChange={(e) => void attach(e.target.files)}/>
              <button disabled={busy} className={styles.outline} onClick={() => picker.current?.click()}>＋ Upload documents or code</button>
              {detail?.assets.map((f) => <p key={f.id} className={styles.file}>▤ {f.name}<small>{f.kind}</small></p>)}
              <p className={styles.hint}>Owner-chosen files only · 8 MiB each. Files are not executed.</p>
            </section>
            <section className={styles.panel}><h2>Approved memory <span>{detail?.memories.length ?? 0}</span></h2>
              <textarea maxLength={1500} value={memory} onChange={(e) => setMemory(e.target.value)} placeholder="A project fact or preference to keep…"/>
              <button className={styles.outline} disabled={busy || memory.trim().length < 3} onClick={() => void saveMemory()}>Remember explicitly</button>
              {detail?.memories.map((note) => <div key={note.id} className={styles.memory}>{note.content}
                <button onClick={() => void removeMemory(note.id)} title="Remove memory" aria-label="Remove memory">×</button></div>)}
            </section>
            <section className={styles.panel}><h2>Built-in skills</h2>
              {overview?.skills.map((skill) => <div className={styles.skill} key={skill.id}><strong>{skill.title}</strong><small>{skill.description}</small></div>)}
              <p className={styles.hint}>No untrusted plugin code or unrestricted host shell runs.</p>
            </section>
          </aside>
        </div>
        <div className={styles.compose}><textarea value={prompt} disabled={busy} maxLength={6000}
          onChange={(e) => setPrompt(e.target.value)} placeholder="Describe the outcome you want. MioAgent will select bounded tools automatically…"
          onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); void send(); } }}/>
          <button disabled={busy || prompt.trim().length < 4} onClick={() => void send()}>{busy ? "…" : "↑"}</button>
          <small>Ctrl+Enter · Live research, project files and local model review · No unrestricted computer actions</small></div>
      </>}
    </main>
  </div>;
}
