"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

type TaskStatus = "queued" | "running" | "completed" | "failed" | "canceled";
type TaskKind = "demo_workflow" | "workspace_inventory" | "echo";
type Task = {
  id: string; kind: TaskKind; prompt: string; status: TaskStatus; progress: number;
  result: Record<string, unknown> | null; error: string | null;
  created_at: string; updated_at: string;
};
type System = {
  name: string; version: string; stage: string; mode: string;
  ai_model_connected: boolean; voice_enabled: boolean;
  computer_control_enabled: boolean; task_counts: Record<string, number>;
};

const kinds: Record<TaskKind, { name: string; desc: string }> = {
  demo_workflow: { name: "Workflow demonstration", desc: "Run five real tracked worker steps; no AI model involved." },
  workspace_inventory: { name: "Workspace inventory", desc: "Inspect safe filenames inside the read-only project volume." },
  echo: { name: "Echo test", desc: "Verify the task API and persistent results using your text." },
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/proxy/${path}`, { cache: "no-store", ...init });
  if (!response.ok) {
    let message = `${response.status}: ${response.statusText}`;
    try { const detail = await response.json(); message = detail.detail ?? message; } catch { /* use status */ }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export default function Home() {
  const [system, setSystem] = useState<System | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [kind, setKind] = useState<TaskKind>("demo_workflow");
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [view, setView] = useState<"overview" | "activity" | "settings">("overview");
  const [lastSync, setLastSync] = useState<string>("—");

  const refresh = useCallback(async () => {
    try {
      const [info, list] = await Promise.all([
        api<System>("status"), api<{ tasks: Task[] }>("tasks"),
      ]);
      setSystem(info);
      setTasks(list.tasks);
      setLastSync(new Date().toLocaleTimeString());
      setError("");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Could not connect to backend");
    }
  }, []);

  useEffect(() => {
    void refresh();
    const interval = setInterval(() => void refresh(), 2000);
    return () => clearInterval(interval);
  }, [refresh]);

  const counts = useMemo(() => ({
    running: tasks.filter((t) => t.status === "running").length,
    queued: tasks.filter((t) => t.status === "queued").length,
    completed: tasks.filter((t) => t.status === "completed").length,
    failed: tasks.filter((t) => t.status === "failed").length,
  }), [tasks]);

  async function submit() {
    setBusy(true);
    try {
      const task = await api<Task>("tasks", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, prompt }),
      });
      setSelected(task.id);
      if (kind === "echo") setPrompt("");
      setView("activity");
      await refresh();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Could not create task");
    } finally { setBusy(false); }
  }

  async function cancel(id: string) {
    try { await api(`tasks/${id}/cancel`, { method: "POST" }); await refresh(); }
    catch (exc) { setError(exc instanceof Error ? exc.message : "Could not cancel task"); }
  }

  const selectedTask = tasks.find((t) => t.id === selected) ?? tasks[0];
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">✦</span><div><strong>MioAgent</strong><small>COMMAND CENTER</small></div></div>
        <div className="nav-label">WORKSPACE</div>
        <button className={`nav-item ${view === "overview" ? "active" : ""}`} onClick={() => setView("overview")}><span>◈</span> Overview</button>
        <button className={`nav-item ${view === "activity" ? "active" : ""}`} onClick={() => setView("activity")}><span>▤</span> Task activity</button>
        <button className={`nav-item ${view === "settings" ? "active" : ""}`} onClick={() => setView("settings")}><span>⚙</span> Capabilities</button>
        <div className="sidebar-foot"><span className="status-dot" /> Local-first foundation <small>v0.1.0 · Phase 1</small></div>
      </aside>
      <main className="main">
        <header className="topbar"><span>WORKSTATION / {view.toUpperCase()}</span><div><span className="muted">Synced {lastSync}</span><span className="pill">LOCAL ONLY</span></div></header>
        <div className="content">
          <div className="hero"><div className="hero-kicker">MIOAGENT / SYSTEM CONSOLE</div><h1>Your AI command center<span>.</span></h1><p>The foundation is live. Agent reasoning, voice and computer automation are scheduled for later development phases.</p></div>
          {error && <div role="alert" className="alert">Connection or task error: {error}</div>}
          {view === "overview" && <>
            <section className="stats">
              <div className="stat"><label>BACKEND</label><b>{system ? "Online" : "Connecting"}</b><span>FastAPI / PostgreSQL</span></div>
              <div className="stat"><label>RUNNING</label><b>{counts.running}</b><span>Background work items</span></div>
              <div className="stat"><label>QUEUED</label><b>{counts.queued}</b><span>Waiting to execute</span></div>
              <div className="stat"><label>COMPLETED</label><b>{counts.completed}</b><span>From recent task history</span></div>
            </section>
            <div className="two-col">
              <section className="panel"><div className="panel-title"><h2>Create a task</h2><span className="tag">PHASE 1</span></div>
                <p className="hint">These are real persisted worker operations, not pretend AI results.</p>
                <label className="field-label" htmlFor="kind">TASK TYPE</label>
                <select id="kind" value={kind} onChange={(e) => setKind(e.target.value as TaskKind)}>{Object.entries(kinds).map(([key, value]) => <option value={key} key={key}>{value.name}</option>)}</select>
                <p className="field-help">{kinds[kind].desc}</p>
                <label className="field-label" htmlFor="prompt">DESCRIPTION / INPUT</label>
                <textarea id="prompt" value={prompt} onChange={(e) => setPrompt(e.target.value)} maxLength={4000} placeholder={kind === "echo" ? "Write something to echo..." : "Optional task note..."} />
                <button className="primary-button" onClick={submit} disabled={busy || !system || (kind === "echo" && !prompt.trim())}>{busy ? "Submitting..." : "Create task ↗"}</button>
              </section>
              <section className="panel"><div className="panel-title"><h2>System readiness</h2><span className="tag good">FOUNDATION</span></div>
                <div className="readiness"><span>API and task store</span><strong className={system ? "good-text" : ""}>{system ? "Operational" : "Waiting"}</strong></div>
                <div className="readiness"><span>Persistent background worker</span><strong className={system ? "good-text" : ""}>{system ? "Operational" : "Waiting"}</strong></div>
                <div className="readiness"><span>AI model connection</span><strong>Not configured</strong></div>
                <div className="readiness"><span>Voice recognition</span><strong>Not implemented</strong></div>
                <div className="readiness"><span>Computer control</span><strong>Disabled</strong></div>
                <p className="hint bottom-note">This screen does not claim capabilities that have not yet been built or authorized.</p>
              </section>
            </div>
            <section className="panel"><div className="panel-title"><h2>Recent activity</h2><button className="link-button" onClick={() => setView("activity")}>View all →</button></div><TaskRows tasks={tasks.slice(0,5)} onSelect={(id) => { setSelected(id); setView("activity"); }} /></section>
          </>}
          {view === "activity" && <div className="two-col tasks-layout"><section className="panel"><div className="panel-title"><h2>Task queue</h2><span className="tag">{tasks.length} ITEMS</span></div><TaskRows tasks={tasks} onSelect={setSelected} /></section>
            <section className="panel"><div className="panel-title"><h2>Task details</h2><span className="tag">LIVE DATA</span></div>
              {!selectedTask ? <p className="hint">No task yet. Create a task from Overview.</p> : <>
                <div className="task-title">{kinds[selectedTask.kind]?.name ?? selectedTask.kind}</div>
                <div className="task-id">{selectedTask.id}</div>
                <div className="task-meta"><span className={`state ${selectedTask.status}`}>{selectedTask.status}</span><span>{selectedTask.progress}% complete</span></div>
                <div className="progress"><div style={{ width: `${selectedTask.progress}%` }} /></div>
                <h3>Result / progress data</h3><pre>{JSON.stringify(selectedTask.result ?? { message: "Waiting for results" }, null, 2)}</pre>
                {selectedTask.error && <p className="alert">{selectedTask.error}</p>}
                {(selectedTask.status === "queued" || selectedTask.status === "running") && <button className="secondary-button" onClick={() => void cancel(selectedTask.id)}>Cancel task</button>}
              </>}
            </section></div>}
          {view === "settings" && <section className="panel"><div className="panel-title"><h2>Planned capability activation</h2><span className="tag">READ ONLY</span></div>
            <p className="hint">No capability switches are provided until their permission enforcement is built and tested.</p>
            {[["Model routing", "Phase 2"], ["Voice input/output", "Phase 3"], ["Workspace coding tools", "Phase 4"], ["Browser automation", "Phase 4"], ["Continuous research and learning", "Phase 6"]].map(([name, phase]) => <div className="readiness" key={name}><span>{name}</span><strong>{phase}</strong></div>)}
          </section>}
          <footer>© MioAgent · Master plan v1.0 · Local dashboard · No external access configured</footer>
        </div>
      </main>
    </div>
  );
}

function TaskRows({ tasks, onSelect }: { tasks: Task[]; onSelect: (id: string) => void }) {
  if (!tasks.length) return <p className="hint">No tasks recorded yet.</p>;
  return <div className="task-list">{tasks.map((task) => <button key={task.id} className="task-row" onClick={() => onSelect(task.id)}>
    <span className="task-icon">▣</span><span className="task-name"><strong>{kinds[task.kind]?.name ?? task.kind}</strong><small>{new Date(task.created_at).toLocaleString()}</small></span>
    <span className={`state ${task.status}`}>{task.status}</span><span className="task-arrow">›</span>
  </button>)}</div>;
}
