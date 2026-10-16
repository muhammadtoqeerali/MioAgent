"use client";

import { useCallback, useEffect, useState } from "react";

type DraftFile = { path: string; content: string; bytes: number; sha256: string };
type Draft = { plan: string[]; files: DraftFile[]; checks: string[]; verification: string;
  file_count: number; total_bytes: number };
type Project = { id: string; title: string; requirements: string; status: string;
  workspace: string | null; draft_task_id: string | null; apply_task_id: string | null;
  error: string | null; draft?: Draft | null };
type Repair = { status: string; result: {
  diagnosis: string; changed_files: string[];
  candidate: Draft; review_required: boolean; executed: boolean;
} | null; error?: string | null };
type Verification = { status: string; result: {
  outcome: string; passed: boolean; tests_run: number; log: string; executed: boolean;
  isolation?: string; return_code?: number
} | null; error?: string | null };

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/proxy/${path}`, { cache: "no-store", ...init });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail ?? `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [title, setTitle] = useState("");
  const [requirements, setRequirements] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [verification, setVerification] = useState<Verification | null>(null);
  const [repair, setRepair] = useState<Repair | null>(null);
  const [repairFile, setRepairFile] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const listing = await api<{ projects: Project[] }>("projects");
      setProjects(listing.projects);
      if (active) {
        const detail = await api<Project>(`projects/${encodeURIComponent(active)}`);
        setProject(detail);
        if (detail.status === "completed") {
          setVerification(await api<Verification>(`projects/${encodeURIComponent(active)}/verification`));
          setRepair(await api<Repair>(`projects/${encodeURIComponent(active)}/repair`));
        } else {
          setVerification(null);
          setRepair(null);
        }
      }
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Project backend unavailable");
    }
  }, [active]);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (!active || !project || (!["drafting", "applying"].includes(project.status) &&
      !["queued", "running"].includes(verification?.status ?? "") &&
      !["queued", "running"].includes(repair?.status ?? ""))) return;
    const interval = setInterval(() => void refresh(), 1600);
    return () => clearInterval(interval);
  }, [active, project, verification?.status, repair?.status, refresh]);

  async function create() {
    if (title.trim().length < 3 || requirements.trim().length < 20 || busy) return;
    setBusy(true); setError("");
    try {
      const created = await api<Project>("projects", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: title.trim(), requirements: requirements.trim() }),
      });
      setActive(created.id); setProject(created); setTitle(""); setRequirements("");
      await api<{ projects: Project[] }>("projects").then(data => setProjects(data.projects));
    } catch (e) { setError(e instanceof Error ? e.message : "Cannot create project"); }
    finally { setBusy(false); }
  }

  async function approve() {
    if (!active || !project || project.status !== "review" || busy) return;
    setBusy(true); setError("");
    try {
      const result = await api<Project>(`projects/${encodeURIComponent(active)}/apply`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved: true }),
      });
      setProject(result); await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : "Approval could not be applied"); }
    finally { setBusy(false); }
  }

  async function verify() {
    if (!active || project?.status !== "completed" || busy) return;
    setBusy(true); setError("");
    try {
      const queued = await api<Verification>(`projects/${encodeURIComponent(active)}/verify`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved: true }),
      });
      setVerification(queued);
    } catch (e) { setError(e instanceof Error ? e.message : "Sandbox verification unavailable"); }
    finally { setBusy(false); }
  }

  async function requestRepair() {
    if (!active || busy) return;
    setBusy(true); setError("");
    try {
      const queued = await api<Repair>(`projects/${encodeURIComponent(active)}/repair`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved: true }),
      });
      setRepair(queued);
    } catch (e) { setError(e instanceof Error ? e.message : "Repair unavailable"); }
    finally { setBusy(false); }
  }

  async function promoteRepair() {
    if (!active || busy || repair?.status !== "completed") return;
    setBusy(true); setError("");
    try {
      const revision = await api<Project>(`projects/${encodeURIComponent(active)}/repair/use`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved: true }),
      });
      setActive(revision.id); setProject(revision); setRepair(null); setSelectedFile(null);
      setRepairFile(null);
      await api<{ projects: Project[] }>("projects").then(r => setProjects(r.projects));
    } catch (e) { setError(e instanceof Error ? e.message : "Cannot create revision"); }
    finally { setBusy(false); }
  }

  async function cancel() {
    const taskId = project?.status === "drafting" ? project?.draft_task_id : project?.apply_task_id;
    if (!taskId || busy) return;
    setBusy(true); setError("");
    try { await api(`tasks/${encodeURIComponent(taskId)}/cancel`, { method: "POST" }); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : "Cancellation failed"); }
    finally { setBusy(false); }
  }

  const shown = project?.draft?.files.find(f => f.path === selectedFile) ?? project?.draft?.files[0];
  return <div className="ai-shell">
    <aside className="ai-nav">
      <div className="ai-brand">✦ &nbsp; MioAgent <small>PROJECT MODE · EARLY RELEASE</small></div>
      <a className="ai-back" href="/assistant">← Chat Mode</a>
      <a className="ai-back" href="/">← Command center</a>
      <div className="ai-subtitle">PROJECTS</div>
      <button className="ai-new" onClick={() => { setActive(null); setProject(null); setError(""); }}>
        ＋ New project
      </button>
      {projects.map(p => <button key={p.id} className={`ai-conv ${active === p.id ? "selected" : ""}`}
        onClick={() => { setActive(p.id); setProject(p); setSelectedFile(null); }}>
        {p.title} · {p.status}
      </button>)}
    </aside>
    <main className="ai-main">
      <div className="ai-header"><div><strong>Autonomous Project Mode</strong>
        <div className="ai-muted">Local model → reviewed files → optional isolated test verification</div>
      </div><div className="ai-chip">No arbitrary commands · No paid APIs</div></div>
      {error && <div className="ai-error" role="alert">{error}</div>}
      {!active ? <div className="ai-memory project-form">
        <h2>Start a coding project</h2>
        <p>This first Project Mode generates small project source files for review. It does not run code,
          browse the internet, install packages, or push to GitHub. Only explicitly approved drafts are saved.
          Project Mode must be enabled by the workstation administrator.</p>
        <label className="field-label" htmlFor="project-title">PROJECT NAME</label>
        <input id="project-title" value={title} maxLength={140}
          onChange={e => setTitle(e.target.value)} placeholder="My Python utility" />
        <label className="field-label" htmlFor="project-requirements">REQUIREMENTS</label>
        <textarea id="project-requirements" value={requirements} maxLength={6000}
          onChange={e => setRequirements(e.target.value)}
          placeholder="Describe what to implement, the files you need, and acceptance criteria..." />
        <button disabled={busy || title.trim().length < 3 || requirements.trim().length < 20}
          onClick={() => void create()}>{busy ? "Preparing…" : "Generate reviewable draft →"}</button>
      </div> : <div className="ai-memory project-detail">
        <div className="project-heading"><h2>{project?.title ?? "Loading project…"}</h2>
          <span className="state">{project?.status ?? "loading"}</span></div>
        <p>{project?.requirements}</p>
        {project?.error && <div className="ai-error" role="alert">{project.error}</div>}
        {["drafting", "applying"].includes(project?.status ?? "") && <div className="ai-running">
          <strong>{project?.status === "drafting" ? "Local model drafting project files…" : "Saving approved files…"}</strong>
          <p>Task status is stored persistently. Refreshing this page will not create a duplicate task.</p>
          <button className="ai-cancel" disabled={busy} onClick={() => void cancel()}>Cancel</button>
        </div>}
        {project?.draft && <>
          <div className="project-summary"><div><strong>{project.draft.file_count} files</strong>
            <small>{project.draft.total_bytes.toLocaleString()} generated bytes</small></div>
            <div><strong>Static checks</strong><small>{project.draft.checks.length} checks</small></div></div>
          <h3>Proposed implementation</h3>
          <ol>{project.draft.plan.map((step, i) => <li key={i}>{step}</li>)}</ol>
          <h3>Generated file preview</h3>
          <div className="project-file-tabs">{project.draft.files.map(file =>
            <button key={file.path} className={shown?.path === file.path ? "active" : ""}
              onClick={() => setSelectedFile(file.path)}>{file.path}</button>)}</div>
          {shown && <pre className="project-code">{shown.content}</pre>}
          <p className="project-warning">{project.draft.verification}. Review every file before approving.
            Testing requires separate approval and workstation sandbox enablement.</p>
          {project.status === "review" && <button className="project-approve" disabled={busy}
            onClick={() => void approve()}>{busy ? "Applying…" : "I approve writing these files →"}</button>}
          {project.status === "completed" && <p className="project-success">
            Approved source was saved to <code>{project.workspace}</code>.
          </p>}
          {project.status === "completed" && <section>
            <h3>Optional isolated unit-test verification</h3>
            <p>Only approved test_*.py files can run. Bubblewrap blocks network access and does not mount
              your personal files or GPUs. This is not autonomous repair or a security guarantee.</p>
            <button className="project-approve" disabled={busy || ["queued", "running"].includes(verification?.status ?? "")}
              onClick={() => void verify()}>{busy ? "Starting…" : "I approve sandbox test execution →"}</button>
            {verification && verification.status !== "not_run" && <div className="project-summary">
              <strong>Verification: {verification.status}</strong>
              {verification.result && <div>
                <p>{verification.result.outcome} · {verification.result.tests_run} tests run ·
                  {verification.result.passed ? " passed" : " not passed"}</p>
                <pre className="project-code">{verification.result.log}</pre>
              </div>}
              {verification.error && <p role="alert">{verification.error}</p>}
            </div>}
          </section>}
          {project.status === "completed" && verification?.status === "completed" &&
            verification.result?.executed === true && verification.result.passed === false &&
            verification.result.outcome === "failed" && <section>
            <h3>Local AI repair proposal</h3>
            <p>Repair proposals replace existing application Python source only.
              Your tests and approved original project remain unchanged.
              No repair is executed until you review, approve, and verify the new revision.</p>
            {(!repair || repair.status === "not_run") &&
              <button disabled={busy} onClick={() => void requestRepair()}>
                Propose a fix using local model →
              </button>}
            {repair && ["queued", "running"].includes(repair.status) &&
              <p>Local model is analyzing failed tests…</p>}
            {repair?.status === "failed" && <p role="alert">{repair.error ?? "Repair proposal failed"}</p>}
            {repair?.status === "completed" && repair.result && <>
              <p><strong>Diagnosis:</strong> {repair.result.diagnosis}</p>
              <div className="project-file-tabs">{repair.result.changed_files.map(p =>
                <button key={p} className={repairFile === p ? "active" : ""}
                  onClick={() => setRepairFile(p)}>{p}</button>)}</div>
              <pre className="project-code">{repair.result.candidate.files.find(
                f => f.path === (repairFile ?? repair.result?.changed_files[0]))?.content}</pre>
              <p className="project-warning">Not executed, not tested. Existing tests are unchanged.</p>
              <button className="project-approve" disabled={busy}
                onClick={() => void promoteRepair()}>Create reviewable repair revision →</button>
            </>}
            </section>}
        </>}
      </div>}
      <footer className="ai-footer">Guarded Python unittest verification and reviewable, local-only repair proposals. No shell, browser, automatic patch application, or unattended completion.</footer>
    </main>
  </div>;
}
