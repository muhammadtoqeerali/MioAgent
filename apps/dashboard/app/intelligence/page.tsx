"use client";

import { useCallback, useEffect, useState } from "react";
import styles from "./intelligence.module.css";

type Model = { id: string; size_bytes: number | null; selected: boolean };
type RepoRun = { id: string; state: string; model: string | null; planner_model: string | null;
  tests_run: number; baseline_passed: boolean | null; changed_files: string[];
  attempt_count: number; applied: boolean; patch_available: boolean; created_unix: number | null };
type GoalRun = { id: string; state: string; model: string | null; project_id: string | null;
  outcome: string | null };
type Summary = { release: string; models: Model[]; fleet_active: boolean;
  routes: Record<string, string[]>; repo_runs: RepoRun[]; goal_runs: GoalRun[];
  warning: string | null; capabilities: Record<string, boolean>; read_only: boolean };

async function read<T>(path: string): Promise<T> {
  const response = await fetch(`/api/proxy/${path}`, { cache: "no-store" });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail ?? `API returned ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function short(value: string, length = 14): string {
  return value.length > length ? `${value.slice(0, length)}…` : value;
}

export default function IntelligencePage() {
  const [data, setData] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState<string>("Not yet synced");
  const [patch, setPatch] = useState<string | null>(null);
  const [patchId, setPatchId] = useState<string | null>(null);
  const [patchError, setPatchError] = useState<string | null>(null);
  const [patchBusy, setPatchBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const current = await read<Summary>("intelligence/overview");
      setData(current);
      setLoaded(new Date().toLocaleTimeString());
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Dashboard backend unavailable");
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), 15000);
    return () => clearInterval(timer);
  }, [refresh]);

  async function showPatch(id: string) {
    setPatchBusy(true);
    setPatchError(null);
    setPatch(null);
    setPatchId(id);
    try {
      const result = await read<{ id: string; patch: string }>(`intelligence/repository/${id}/patch`);
      setPatch(result.patch);
    } catch (exc) {
      setPatchError(exc instanceof Error ? exc.message : "Could not load patch");
    } finally {
      setPatchBusy(false);
    }
  }

  return (
    <div className={styles.shell}>
      <aside className={styles.nav}>
        <a href="/" className={styles.logo}>✦ <strong>MioAgent</strong><span>ENGINEERING CONSOLE</span></a>
        <span className={styles.navHeading}>WORKSPACE</span>
        <a href="/">◈ &nbsp; Overview</a>
        <a href="/assistant">✦ &nbsp; AI Assistant</a>
        <a href="/projects">▣ &nbsp; Project Mode</a>
        <a className={styles.current} href="/intelligence">◉ &nbsp; Intelligence &amp; Engineering</a>
        <div className={styles.navFoot}>LOCAL-FIRST · OWNER CONTROLLED
          <small>UI release v0.4F</small>
        </div>
      </aside>
      <main className={styles.main}>
        <header className={styles.top}>
          <span>WORKSTATION / INTELLIGENCE</span>
          <span>Last sync: {loaded} &nbsp; <button type="button" onClick={() => void refresh()}>Refresh ↻</button></span>
        </header>
        <div className={styles.content}>
          <div className={styles.hero}>
            <span className={styles.eyebrow}>MIOAGENT / VERIFIED CAPABILITIES</span>
            <h1>Your local intelligence fleet<span>.</span></h1>
            <p>Live local models, bounded repository engineering, and audited test evidence.
              This page is read-only: it never executes code, changes a model policy, or applies a patch.</p>
            <div className={styles.chips}><span>v0.4F DASHBOARD</span><span>LOCAL API</span><span>READ-ONLY EVIDENCE</span></div>
          </div>
          {error && <div role="alert" className={styles.error}>{error}. Confirm that the Ubuntu API and SSH tunnel are running.</div>}
          {data?.warning && <div role="status" className={styles.warning}>{data.warning}</div>}
          <div className={styles.stats}>
            <div className={styles.stat}><small>INSTALLED MODELS</small><strong>{data?.models.length ?? "—"}</strong><span>Detected from the local Ollama service</span></div>
            <div className={styles.stat}><small>MULTI-MODEL ROUTING</small><strong>{data ? data.fleet_active ? "Active" : "Baseline" : "—"}</strong><span>Preferred models per task role</span></div>
            <div className={styles.stat}><small>REPOSITORY RUNS</small><strong>{data?.repo_runs.length ?? "—"}</strong><span>Saved local engineering evidence</span></div>
            <div className={styles.stat}><small>PASSING REPO RUNS</small><strong>{data?.repo_runs.filter(run => run.state === "passed").length ?? "—"}</strong><span>Owner-selected tests, not model opinions</span></div>
          </div>
          <div className={styles.twocol}>
            <section className={styles.panel}>
              <div className={styles.panelHead}><h2>Installed Ollama models</h2><span className={styles.tag}>LIVE INVENTORY</span></div>
              {!data && <p>Loading local models…</p>}
              {data && data.models.length === 0 && <p>No local models reported. Ollama may be offline.</p>}
              {data?.models.map(model => <div className={styles.model} key={model.id}>
                <div><strong>{model.id}</strong><small>{model.size_bytes == null ? "Size unavailable" : `${(model.size_bytes / 1e9).toFixed(1)} GB installed`}</small></div>
                <span className={model.selected ? styles.good : styles.tag}>{model.selected ? "ROUTED" : "AVAILABLE"}</span>
              </div>)}
              <p className={styles.note}>Installed on disk does not mean loaded in GPU memory. The fleet is sequential by default.</p>
            </section>
            <section className={styles.panel}>
              <div className={styles.panelHead}><h2>Task-role routing</h2><span className={data?.fleet_active ? styles.good : styles.tag}>{data?.fleet_active ? "ACTIVE" : "NOT ACTIVE"}</span></div>
              {data && !data.fleet_active && <p>The default local model is used until the owner activates a fleet.</p>}
              {data && Object.entries(data.routes).sort(([a], [b]) => a.localeCompare(b)).map(([role, names]) => <div key={role} className={styles.route}>
                <strong>{role}</strong><span>{names.join(" → ")}</span>
              </div>)}
              <p className={styles.note}>Fallback priority is not a guarantee that every request uses multiple models. Independent review is an explicit step.</p>
            </section>
          </div>
          <section className={styles.panel}>
            <div className={styles.panelHead}><h2>Existing-repository engineering</h2><span className={styles.tag}>v0.4E TEST EVIDENCE</span></div>
            {!data && <p>Reading verified run records…</p>}
            {data && data.repo_runs.length === 0 && <p>No repository engineering runs recorded in the private runtime.</p>}
            {data?.repo_runs.map(run => <div key={run.id} className={styles.run}>
              <div className={styles.runTop}>
                <div><strong>Repository run {short(run.id)}</strong><small>{run.created_unix ? new Date(run.created_unix * 1000).toLocaleString() : "Timestamp unavailable"} · {run.model ?? "No coding model recorded"}</small></div>
                <span className={run.state === "passed" ? styles.good : styles.tag}>{run.state.toUpperCase()}</span>
              </div>
              <div className={styles.runMetrics}>
                <span>Tests: <b>{run.tests_run}</b></span><span>Baseline: <b>{run.baseline_passed === false ? "Failed" : run.baseline_passed ? "Passed" : "Unknown"}</b></span>
                <span>Attempts: <b>{run.attempt_count}</b></span><span>Original source: <b>{run.applied ? "Applied" : "Unchanged"}</b></span>
              </div>
              {run.changed_files.length > 0 && <p className={styles.changed}>Changed: {run.changed_files.join(", ")}</p>}
              {run.patch_available && <button type="button" className={styles.patchButton} onClick={() => void showPatch(run.id)}>View verified diff →</button>}
            </div>)}
          </section>
          {patchId && <section className={styles.panel}>
            <div className={styles.panelHead}><h2>Review patch {short(patchId)}</h2><button onClick={() => { setPatchId(null); setPatch(null); }} type="button">Close ×</button></div>
            {patchBusy && <p>Loading saved patch…</p>}
            {patchError && <div role="alert" className={styles.error}>{patchError}</div>}
            {patch != null && <pre className={styles.diff}>{patch}</pre>}
            <p className={styles.note}>Patch preview only. Applying verified bytes requires the separate owner-authorized CLI command and fresh test verification.</p>
          </section>}
          <section className={styles.panel}>
            <div className={styles.panelHead}><h2>Goal-driven engineering history</h2><span className={styles.tag}>PRIVATE RUN REPORTS</span></div>
            {data && data.goal_runs.length === 0 && <p>No saved goal-driven engineering reports.</p>}
            {data?.goal_runs.map(run => <div className={styles.goalRow} key={run.id}>
              <span>{short(run.id, 22)}</span><strong>{run.outcome ?? run.state}</strong><small>{run.model ?? "Model not recorded"}</small>
            </div>)}
          </section>
          <section className={styles.panel}>
            <div className={styles.panelHead}><h2>Capability boundaries</h2><span className={styles.tag}>IMPLEMENTED VS PLANNED</span></div>
            <div className={styles.capabilities}>
              {data && Object.entries(data.capabilities).map(([key, enabled]) => <div key={key}>
                <span>{key.replaceAll("_", " ")}</span><strong className={enabled ? styles.yes : styles.no}>{enabled ? "Available" : "Not implemented"}</strong>
              </div>)}
            </div>
          </section>
          <footer className={styles.footer}>MioAgent v0.4F · Authenticated localhost data · No background inference from this dashboard</footer>
        </div>
      </main>
    </div>
  );
}
