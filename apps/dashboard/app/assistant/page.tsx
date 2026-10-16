"use client";

import { useCallback, useEffect, useState } from "react";

type ModelInfo = { configured: boolean; route: string; local_model: string | null;
  cloud_enabled: boolean; cloud_model: string | null; local_reachable: boolean };
type Conversation = { id: string; title: string; updated_at: string };
type ChatMessage = { id: string; role: string; content: string; task_id: string | null };
type Run = { id: string; status: string; progress: number; error: string | null;
  result: { stage?: string; plan?: string[]; answer?: string;
    model?: string; provider?: string; input_tokens?: number; output_tokens?: number } | null };
type Memory = { id: string; content: string };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/proxy/${path}`, { cache: "no-store", ...init });
  if (!response.ok) {
    const json = await response.json().catch(() => null);
    throw new Error(json?.detail ?? `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export default function Assistant() {
  const [model, setModel] = useState<ModelInfo | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [prompt, setPrompt] = useState("");
  const [running, setRunning] = useState<string | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [note, setNote] = useState("");
  const [tab, setTab] = useState<"chat" | "memory">("chat");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [config, list, saved] = await Promise.all([
        request<ModelInfo>("assistant/status"),
        request<{ conversations: Conversation[] }>("assistant/conversations"),
        request<{ memories: Memory[] }>("assistant/memories"),
      ]);
      setModel(config);
      setConversations(list.conversations);
      setMemories(saved.memories);
    } catch (e) { setError(e instanceof Error ? e.message : "Connection failed"); }
  }, []);

  const loadConversation = useCallback(async (id: string) => {
    try {
      const data = await request<{ messages: ChatMessage[] }>(`assistant/conversations/${id}`);
      setMessages(data.messages);
    } catch (e) { setError(e instanceof Error ? e.message : "History unavailable"); }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => { if (active) void loadConversation(active); }, [active, loadConversation]);
  useEffect(() => {
    if (!running) return;
    let canceled = false;
    async function poll() {
      if (!running || canceled) return;
      try {
        const current = await request<Run>(`tasks/${running}`);
        if (canceled) return;
        setRun(current);
        if (["completed", "failed", "canceled"].includes(current.status)) {
          setRunning(null);
          setPending(false);
          if (active) await loadConversation(active);
          void refresh();
        }
      } catch (e) { if (!canceled) setError(e instanceof Error ? e.message : "Task status unavailable"); }
    }
    void poll();
    const interval = setInterval(() => void poll(), 1700);
    return () => { canceled = true; clearInterval(interval); };
  }, [running, active, loadConversation, refresh]);

  async function send() {
    if (!prompt.trim() || pending || !model?.configured) return;
    setError(""); setPending(true); setRun(null);
    try {
      const queued = await request<{ conversation_id: string; task_id: string }>("assistant/ask", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: prompt.trim(), conversation_id: active }),
      });
      setPrompt(""); setActive(queued.conversation_id); setRunning(queued.task_id);
      await loadConversation(queued.conversation_id); await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : "Cannot submit"); setPending(false); }
  }

  async function saveNote() {
    try {
      await request("assistant/memories", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: note }) });
      setNote(""); await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : "Could not save note"); }
  }
  async function removeNote(id: string) {
    try { await request(`assistant/memories/${id}`, { method: "DELETE" }); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not remove note"); }
  }
  async function cancel() {
    if (running) await request(`tasks/${running}/cancel`, { method: "POST" });
  }

  return <div className="ai-shell">
    <aside className="ai-nav">
      <div className="ai-brand">✦ &nbsp; MioAgent <small>PHASE 2 INTELLIGENCE</small></div>
      <a className="ai-back" href="/">← System dashboard</a>
      <a className="ai-back" href="/projects">▣ Project Mode →</a>
      <button className="ai-new" onClick={() => { setActive(null); setMessages([]); setRun(null); setError(""); }}>＋ New conversation</button>
      <div className="ai-subtitle">CONVERSATIONS</div>
      {conversations.map(c => <button key={c.id} className={`ai-conv ${active === c.id ? "selected" : ""}`}
        onClick={() => { setActive(c.id); setTab("chat"); }}>{c.title}</button>)}
    </aside>
    <main className="ai-main">
      <div className="ai-header">
        <div><strong>AI Supervisor</strong><div className="ai-muted">Multi-step reasoning · persistent task queue</div></div>
        <div className={`ai-chip ${model?.local_reachable ? "ok" : ""}`}>
          {model?.local_reachable ? "● Local model reachable" : model?.configured ? "○ Model configured" : "○ Model not configured"}
        </div>
      </div>
      <div className="ai-tabs">
        <button className={tab === "chat" ? "active" : ""} onClick={() => setTab("chat")}>Assistant</button>
        <button className={tab === "memory" ? "active" : ""} onClick={() => setTab("memory")}>Approved memory ({memories.length})</button>
      </div>
      {error && <div className="ai-error" role="alert">{error}</div>}
      {tab === "chat" ? <>
        <div className="ai-thread">
          {!model?.configured && <div className="ai-empty"><h2>Connect a model to activate AI</h2>
            <p>Set MIO_LOCAL_MODEL in the protected native configuration and start Ollama on the workstation. No model call is simulated.</p></div>}
          {model?.configured && messages.length === 0 && <div className="ai-empty"><h2>What would you like MioAgent to work on?</h2>
            <p>Your requests run through a descriptive planning stage and a real model response. No computer or browser tools are enabled yet.</p></div>}
          {messages.map(m => <div key={m.id} className={`ai-message ${m.role}`}>
            <div className="ai-role">{m.role === "assistant" ? "MioAgent" : "You"}</div><div className="ai-message-body">{m.content}</div>
          </div>)}
          {run && <div className="ai-running"><strong>{run.status} · {run.progress}%</strong>
            <div className="ai-bar"><span style={{ width: `${run.progress}%` }}/></div>
            {run.result?.plan && <ol>{run.result.plan.map((step, i) => <li key={i}>{step}</li>)}</ol>}
            {run.error && <div className="ai-error">{run.error}</div>}
            {run.result?.model && <div className="ai-muted">Model: {run.result.model} ({run.result.provider})</div>}
            {running && <button className="ai-cancel" onClick={() => void cancel()}>Cancel request</button>}
          </div>}
        </div>
        <div className="ai-compose">
          <textarea aria-label="AI request" maxLength={12000} value={prompt} onChange={e => setPrompt(e.target.value)}
            placeholder={model?.configured ? "Describe your research, coding or writing task..." : "Configure local inference to enable tasks"}
            disabled={!model?.configured || pending} onKeyDown={e => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); void send(); }
            }}/>
          <div className="ai-sendrow"><span>Ctrl + Enter to send · Text-only mode · No autonomous tools</span>
            <button disabled={!model?.configured || !prompt.trim() || pending} onClick={() => void send()}>
              {pending ? "Working…" : "Send to MioAgent →"}</button></div>
        </div>
      </> : <div className="ai-memory">
        <h2>Approved long-term memory</h2>
        <p>Only notes you explicitly save appear here. Relevant notes may be retrieved in future conversations.</p>
        <textarea value={note} maxLength={2000} onChange={e => setNote(e.target.value)} placeholder="Record a useful project decision or preference..." />
        <button disabled={note.trim().length < 3} onClick={() => void saveNote()}>Save memory note</button>
        {memories.map(m => <div key={m.id} className="ai-note"><span>{m.content}</span>
          <button onClick={() => void removeNote(m.id)}>Delete</button></div>)}
      </div>}
      <footer className="ai-footer">Local-first · No autonomous tool execution · Cloud calls disabled by default · Master plan v1.0</footer>
    </main>
  </div>;
}
