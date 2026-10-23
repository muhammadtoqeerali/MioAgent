"use client";
import { useMemo } from "react";

export type ProjectRun={id:string;prompt:string;state:string;mode?:string};
export type Thread={id:string;title:string;count:number};
const PREFIX=/^\[\[SCORPIO_THREAD_V1:([0-9a-f]{32}):([A-Za-z0-9%._~!*()'-]{1,180})\]\]\n/;
const USER_MARK="\n[[SCORPIO_USER_MESSAGE]]\n";

export function inspectThread(prompt:string):{id:string;title:string;message:string}{
 const found=PREFIX.exec(prompt);
 if(!found)return {id:"main",title:"Main discussion",message:prompt};
 let title="New chat";
 try{title=decodeURIComponent(found[2]).slice(0,80)||title;}catch{return {id:"main",title:"Main discussion",message:prompt};}
 const body=prompt.slice(found[0].length);
 const index=body.lastIndexOf(USER_MARK);
 return {id:found[1],title,message:index>=0?body.slice(index+USER_MARK.length):body};
}
export function threadPrompt(id:string,title:string,message:string,history:{prompt:string;result?:string|null}[]):string{
 if(id==="main")return message;
 if(!/^[0-9a-f]{32}$/.test(id))throw new Error("Invalid project discussion identity");
 const safeTitle=encodeURIComponent(title.trim().slice(0,70)||"New chat");
 const conversation=history.slice(-3).map(item=>`User: ${inspectThread(item.prompt).message.slice(0,350)}\nScorpio: ${(item.result??"No completed result").slice(0,550)}`).join("\n\n").slice(-2200);
 const header=`[[SCORPIO_THREAD_V1:${id}:${safeTitle}]]\nThis is a separate project discussion named ${title.slice(0,70)}. Use the shared project instructions, memory and files. Below is bounded context from this discussion only.\n${conversation}\n[[SCORPIO_USER_MESSAGE]]\n`;
 return header+message.slice(0,Math.max(0,5900-header.length));
}
export function listThreads(runs:ProjectRun[]):Thread[]{
 const totals=new Map<string,Thread>([["main",{id:"main",title:"Main discussion",count:0}]]);
 for(const run of runs){const info=inspectThread(run.prompt);const item=totals.get(info.id);if(item)item.count++;else totals.set(info.id,{id:info.id,title:info.title,count:1});}
 return [...totals.values()];
}
export default function ScorpioThreads({runs,selected,onChoose,onNew,pendingTitle}:{runs:ProjectRun[];selected:string;onChoose:(value:string)=>void;onNew:()=>void;pendingTitle:string}){
 const threads=useMemo(()=>listThreads(runs),[runs]);
 return <div className="scorpio8a-threadBar"><div><strong>Project chats</strong><small>Saved conversations grouped from project Work runs</small></div><div className="scorpio8a-threadScroll">{threads.map(t=><button key={t.id} aria-pressed={selected===t.id} className={selected===t.id?"scorpio8a-thread active":"scorpio8a-thread"} onClick={()=>onChoose(t.id)} title={`${t.count} saved turns`}>{t.title} <small>{t.count}</small></button>)}{!threads.some(t=>t.id===selected)&&selected!=="main"&&<button className="scorpio8a-thread active" onClick={()=>onChoose(selected)}>{pendingTitle} · unsent</button>}</div><button type="button" className="scorpio8a-threadNew" onClick={onNew}>＋ New chat</button></div>;
}
