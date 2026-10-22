"use client";

import { useCallback, useEffect, useState } from "react";
import styles from "./reviews.module.css";

type CaseSummary = { model: string; changed_files: string[]; trusted_tests: number; hidden_tests: number };
type Campaign = { campaign: string; base_commit: string; review_sha256: string; seal_verified: true; cases: Record<string, CaseSummary> };
type Inventory = { campaigns: Campaign[]; permissions: { apply: false; approve: false } };
type DiffView = { campaign: string; case: string; patch: string; patch_sha256: string; review_sha256: string; model: string; changed_files: string[]; trusted_tests: number; hidden_tests: number; seal_verified: true; owner_approved_apply: false; source_applied: false };

async function readJson<T>(path: string): Promise<T> {
  const response = await fetch(`/api/proxy/work/engineering/reviews${path}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Evidence unavailable (${response.status}). No changes were made.`);
  return (await response.json()) as T;
}

export default function EngineeringReviewsPage() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [activeCampaign, setActiveCampaign] = useState<string>("");
  const [activeCase, setActiveCase] = useState<string>("");
  const [detail, setDetail] = useState<DiffView | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);

  const refresh = useCallback(async () => {
    setError("");
    try {
      const list = await readJson<Inventory>("");
      if (list.permissions.apply !== false || list.permissions.approve !== false)
        throw new Error("Unexpected review permissions. Review disabled.");
      setCampaigns(list.campaigns);
      setActiveCampaign((current) => current && list.campaigns.some((c) => c.campaign === current)
        ? current : list.campaigns[0]?.campaign ?? "");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Review unavailable"); }
    finally { setBusy(false); }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    const campaign = campaigns.find((c) => c.campaign === activeCampaign);
    setActiveCase((value) => value && campaign && value in campaign.cases ? value : Object.keys(campaign?.cases ?? {})[0] ?? "");
  }, [campaigns, activeCampaign]);
  useEffect(() => {
    if (!activeCampaign || !activeCase) { setDetail(null); return; }
    let live = true;
    setDetail(null);
    void readJson<DiffView>(`/${encodeURIComponent(activeCampaign)}/diff/${encodeURIComponent(activeCase)}`)
      .then((item) => {
        if (!live) return;
        if (!item.seal_verified || item.owner_approved_apply !== false || item.source_applied !== false)
          throw new Error("Review safety gate failed");
        setDetail(item);
        setError("");
      })
      .catch((cause) => { if (live) setError(cause instanceof Error ? cause.message : "Cannot load patch"); });
    return () => { live = false; };
  }, [activeCampaign, activeCase]);

  const selected = campaigns.find((c) => c.campaign === activeCampaign);
  return <main className={styles.shell}>
    <header className={styles.header}>
      <div><a href="/work">← Work</a><h1>Engineering reviews</h1>
        <p>Authenticated patches and independent tests · Local owner access · Read only</p></div>
      <button type="button" onClick={() => { setBusy(true); void refresh(); }} disabled={busy}>Refresh evidence</button>
    </header>
    <p className={styles.notice}>Evidence review does not authorize patch application, milestone approval, or Git publication.</p>
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {busy && <p>Checking sealed review evidence…</p>}
    {!busy && campaigns.length === 0 && !error && <p>No authenticated sealed engineering campaigns are available.</p>}
    {campaigns.length > 0 && <section className={styles.panel}>
      <label htmlFor="campaign">Sealed campaign</label>
      <select id="campaign" value={activeCampaign} onChange={(event) => { setDetail(null); setActiveCampaign(event.target.value); }}>
        {campaigns.map((c) => <option key={c.campaign} value={c.campaign}>{c.campaign}</option>)}
      </select>
      {selected && <p className={styles.meta}>Sealed review SHA-256: <code>{selected.review_sha256}</code></p>}
      {selected && <div className={styles.cases}>
        {Object.entries(selected.cases).map(([name, item]) => <button type="button" key={name}
          aria-pressed={activeCase === name} className={activeCase === name ? styles.selected : ""}
          onClick={() => setActiveCase(name)}>{name} · {item.trusted_tests} + {item.hidden_tests} tests</button>)}
      </div>}
    </section>}
    {detail && <section className={styles.panel}>
      <h2>{detail.case}</h2>
      <p>Model: {detail.model} · Tests: {detail.trusted_tests} original + {detail.hidden_tests} holdout</p>
      <p>Changed files: {detail.changed_files.join(", ")}</p>
      <p className={styles.meta}>Authenticated patch SHA-256: <code>{detail.patch_sha256}</code></p>
      <pre className={styles.diff} tabIndex={0}><code>{detail.patch}</code></pre>
      <p className={styles.meta}>This display cannot execute, apply, or approve a patch.</p>
    </section>}
  </main>;
}
