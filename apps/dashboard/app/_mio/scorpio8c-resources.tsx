"use client";
import {useEffect, useState} from "react";
import {mioApi} from "./api";

type Cpu = {percent:number|null; logical_cores:number|null;measurement:string};
type Memory = {used_bytes:number;total_bytes:number;available_bytes:number;used_percent:number};
type Volume = {label:string;mount_path:string;total_bytes:number|null;used_bytes:number|null;free_bytes:number|null;used_percent:number|null};
type GPUDevice = {index:number;name:string;gpu_percent:number;memory_used_bytes:number;memory_total_bytes:number;memory_percent:number};
type Snapshot = {sampled_at:string;source:{role:string;hostname:string;scope:string};cpu:Cpu;memory:Memory|null;volumes:Volume[];gpu:{state:string;backend:string;devices:GPUDevice[];note:string};disclaimer:string};
const pct=(v:number|null|undefined)=>typeof v==="number"&&Number.isFinite(v)?`${Math.max(0,Math.min(100,v)).toFixed(1)}%`:"Unavailable";
const amount=(n:number|null|undefined)=>typeof n==="number"&&n>=0&&Number.isFinite(n)?`${(n/1073741824).toFixed(1)} GiB`:"Unknown";
function meter(value:number|null|undefined,kind:string){return <div className="scorpio8c-meter" role="meter" aria-label={kind} aria-valuemin={0} aria-valuemax={100} aria-valuenow={typeof value==="number"?value:undefined} aria-valuetext={pct(value)}><div style={{width:`${typeof value==="number"?Math.max(0,Math.min(100,value)):0}%`}}/></div>}
export default function ScorpioResources(){
 const [value,setValue]=useState<Snapshot|null>(null);
 const [error,setError]=useState("");
 const [loading,setLoading]=useState(true);
 useEffect(()=>{let active=true;const fetchNow=async()=>{try{const result=await mioApi<Snapshot>("system/telemetry");if(active){setValue(result);setError("");}}catch(e){if(active){setError(e instanceof Error?e.message:"Telemetry endpoint unavailable");setValue(null);}}finally{if(active)setLoading(false);}};void fetchNow();const timer=window.setInterval(()=>void fetchNow(),12000);return()=>{active=false;window.clearInterval(timer)}},[]);
 const cpu=value?.cpu.percent,mem=value?.memory,vols=value?.volumes??[],gpus=value?.gpu.devices??[];
 return <section className="scorpio8c-section" aria-label="Measured API host resources">
  <div className="scorpio8c-heading"><div><span className="scorpio8c-overline">MEASURED HARDWARE · READ ONLY</span><h2>System resources</h2><p>CPU, available memory, storage and NVIDIA GPUs sampled on the API host. No synthetic gauges.</p></div><div className="scorpio8c-host"><span>MEASUREMENT SOURCE</span><strong>{value?.source.hostname||"Awaiting telemetry"}</strong><small>{value?.source.scope||"API host only"}</small></div></div>
  {error&&<p className="scorpio8c-warning" role="status">Telemetry unavailable: {error}. The API process may require the separately approved telemetry release. No readings are assumed.</p>}
  <div className="scorpio8c-grid">
   <article className="scorpio8c-card"><div className="scorpio8c-cardTitle"><span className="scorpio8c-dot blue"/>CPU</div><strong>{pct(cpu)}</strong><small>{value?.cpu.logical_cores??"—"} logical cores · 120 ms sample</small>{meter(cpu,"CPU utilization")}</article>
   <article className="scorpio8c-card"><div className="scorpio8c-cardTitle"><span className="scorpio8c-dot purple"/>Memory</div><strong>{pct(mem?.used_percent)}</strong><small>{mem?`${amount(mem.used_bytes)} used · ${amount(mem.available_bytes)} available`:"Unavailable"}</small>{meter(mem?.used_percent,"Memory used")}</article>
   <article className="scorpio8c-card"><div className="scorpio8c-cardTitle"><span className="scorpio8c-dot green"/>GPU</div><strong>{gpus.length?pct(gpus[0].gpu_percent):"Unavailable"}</strong><small>{gpus.length?gpus[0].name:value?.gpu.note||"No NVIDIA sensor reading"}</small>{meter(gpus.length?gpus[0].gpu_percent:null,"GPU utilization")}</article>
   <article className="scorpio8c-card"><div className="scorpio8c-cardTitle"><span className="scorpio8c-dot orange"/>Workspace storage</div><strong>{pct(vols[0]?.used_percent)}</strong><small>{vols[0]?`${amount(vols[0].free_bytes)} free of ${amount(vols[0].total_bytes)}`:"Unavailable"}</small>{meter(vols[0]?.used_percent,"Workspace storage used")}</article>
  </div>
  <div className="scorpio8c-detailGrid"><article className="scorpio8c-list"><h3>Storage volumes</h3>{vols.length?vols.map((v,i)=><div key={`${v.label}-${i}`} className="scorpio8c-volume"><div><strong>{v.label}</strong><small title={v.mount_path}>{v.mount_path}</small></div><span>{amount(v.free_bytes)} free / {amount(v.total_bytes)}</span>{meter(v.used_percent,`${v.label} used`)}</div>):<p>Not measured yet</p>}</article>
   <article className="scorpio8c-list"><h3>Local GPU devices</h3>{gpus.length?gpus.map(g=><div key={g.index} className="scorpio8c-volume"><div><strong>GPU {g.index}: {g.name}</strong><small>{pct(g.gpu_percent)} core load · {amount(g.memory_used_bytes)} / {amount(g.memory_total_bytes)} VRAM</small></div>{meter(g.memory_percent,`GPU ${g.index} VRAM used`)}</div>):<p>{value?.gpu.note||"No GPU telemetry received"}</p>}</article></div>
  <p className="scorpio8c-footer">{loading?"Reading API-host sensors…":value?`Observed ${new Date(value.sampled_at).toLocaleTimeString()}. Measurements are from ${value.source.hostname}, not assumed remote model or agent hosts.`:"No host measurements available."}</p>
 </section>;
}
