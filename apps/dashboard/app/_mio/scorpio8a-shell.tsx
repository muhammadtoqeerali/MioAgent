"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { mioApi, type WorkProject } from "./api";
import ScorpioResources from "./scorpio8c-resources";

type Nav = { name: string; url: string; symbol: string; match: string[] };
const NAV: Nav[] = [
  {name:"Control Room",url:"/control-room",symbol:"◈",match:["/control-room"]},
  {name:"Chat",url:"/chat",symbol:"◉",match:["/chat"]},
  {name:"Projects",url:"/projects-space",symbol:"▦",match:["/projects-space","/projects"]},
  {name:"Work",url:"/work-mode",symbol:"▤",match:["/work-mode","/work"]},
  {name:"Approvals",url:"/approvals",symbol:"◇",match:["/approvals"]},
  {name:"Tools & Permissions",url:"/tools-permissions",symbol:"⬡",match:["/tools-permissions"]},
  {name:"System Health",url:"/system-health",symbol:"◴",match:["/system-health"]},
  {name:"Logs & Events",url:"/activity",symbol:"☷",match:["/activity"]},
  {name:"Settings",url:"/settings",symbol:"⚙",match:["/settings"]},
];
const protectedLegacy = ["/studio", "/assistant", "/intelligence", "/workspace", "/work/reviews"];

type Status = {connected: boolean; projects: WorkProject[]; attention: number; updated: number | null; message: string};
export default function ScorpioShell({children}:{children:ReactNode}){
  const pathname = usePathname();
  const [status,setStatus]=useState<Status>({connected:false,projects:[],attention:0,updated:null,message:"Checking local Work API"});
  const [compact,setCompact]=useState(false);
  const refresh=useCallback(async()=>{
    try {
      const overview=await mioApi<{projects:WorkProject[]}>("work/overview");
      const projects=overview.projects.slice(0,40);
      // Only count states actually returned by the authenticated Work API.
      const results=await Promise.allSettled(projects.map(p=>mioApi<{runs:{state:string}[]}>(`work/projects/${p.id}`)));
      let attention=0;
      for(const outcome of results){if(outcome.status==="fulfilled")attention+=outcome.value.runs.filter(r=>["needs_review","failed","interrupted"].includes(r.state)).length;}
      setStatus({connected:true,projects,attention,updated:Date.now(),message:results.some(r=>r.status==="rejected")?"Some project records unavailable":"Work API connected"});
    }catch(err){setStatus(x=>({...x,connected:false,message:err instanceof Error?err.message:"Local API unavailable"}));}
  },[]);
  useEffect(()=>{void refresh();const poll=window.setInterval(()=>void refresh(),15000);return()=>window.clearInterval(poll);},[refresh]);
  const path=pathname??"/control-room";
  const current=NAV.find(n=>n.match.some(m=>path===m||path.startsWith(m+"/")))??NAV[0];
  const isLegacy=protectedLegacy.some(p=>path===p||path.startsWith(p+"/"));
  return <div className={`scorpio8a-app ${compact?"scorpio8a-compact":""}`}>
    <aside className="scorpio8a-side" aria-label="Scorpio main navigation">
      <Link href="/control-room" className="scorpio8a-brand"><img src="/scorpio-mark.svg?v=8c" alt="Scorpio scorpion logo" width={55} height={55}/><span>Scorpio<small>AI AGENT PLATFORM</small></span></Link>
      <div className="scorpio8a-sideSection">WORKSPACE</div>
      <nav aria-label="Main sections">
        {NAV.map((n,i)=><Link href={n.url} key={n.url} aria-current={current.name===n.name?"page":undefined} className={`scorpio8a-nav ${current.name===n.name?"active":""}`}><span className="scorpio8a-navIcon" aria-hidden="true">{n.symbol}</span><span className="scorpio8a-navLabel">{n.name}</span>{n.name==="Approvals"&&status.attention>0&&<span className="scorpio8a-count">{status.attention}</span>}{i===3&&<span className="scorpio8a-navSep"/>}</Link>)}
      </nav>
      <div className="scorpio8a-sideBottom"><div className="scorpio8a-ownerDot">●</div><strong>Owner workspace</strong><small>Local-first · Authenticated Work</small><button onClick={()=>setCompact(v=>!v)} title="Toggle narrow navigation" aria-label="Toggle sidebar width">{compact?"Expand navigation":"Collapse navigation"}</button></div>
    </aside>
    <section className="scorpio8a-main">
      <header className="scorpio8a-top"><div className="scorpio8a-topText"><div className="scorpio8a-breadcrumb">SCORPIO / {current.name.toUpperCase()}</div><h1>{current.name}</h1></div><div className="scorpio8a-topRight"><span className={`scorpio8a-signal ${status.connected?"ok":"down"}`} title={status.message}>● {status.connected?"Work API connected":"Work API unavailable"}</span><Link href="/approvals" className="scorpio8a-attentionLink">◇ {status.attention} needs review</Link><button className="scorpio8a-refresh" onClick={()=>void refresh()} title="Refresh live status" aria-label="Refresh Work status">↻</button><span className="scorpio8a-userIcon" aria-label="Local owner">◉</span></div></header>
      <div id="scorpio8a-content" className={`scorpio8a-slot ${isLegacy?"scorpio8a-legacy":""}`}>
        {children}
        {(path === "/control-room" || path === "/system-health") && <ScorpioResources/>}
      </div>
      <footer className="scorpio8a-foot"><span>SCORPIO · local workstation</span><span>{status.updated?`Work status checked ${new Date(status.updated).toLocaleTimeString()}`:"Live status pending"}</span><span>Controls enforce backend authorization · No simulated permissions</span></footer>
    </section>
  </div>;
}
