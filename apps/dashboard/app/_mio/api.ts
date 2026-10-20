export async function mioApi<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/proxy/${path}`, { cache: "no-store", ...init });
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(typeof error?.detail === "string" ? error.detail : `MioAgent API returned ${response.status}`);
  }
  return response.json() as Promise<T>;
}
export function postJson(value: unknown): RequestInit {
  return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(value) };
}
export type WorkProject = { id: string; title: string; instructions: string; created: number };
export type WorkSummary = { id: string; project: string; prompt: string; state: string; mode: string; model: string|null };
export type WorkProjectDetail = WorkProject & { assets: { id:string; name:string; kind:string }[]; memories: {id:string; content:string}[]; runs: WorkSummary[] };
export type WorkRun = WorkSummary & { result:string|null; error:string|null; sources: {ref:string; title:string; url:string; snippet:string}[]; events:{phase:string;detail:string;created:number}[] };
export const done = (state: string) => ["answered", "needs_review", "failed", "interrupted"].includes(state);
export const delegationTitle = (title: string) => `Work · ${title}`;
export const isDelegation = (title: string) => title.startsWith("Work · ");
