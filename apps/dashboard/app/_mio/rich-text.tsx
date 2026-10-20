import type { ReactNode } from "react";
import s from "./experience.module.css";
function inline(text: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\(https:\/\/[^\s)]+\))/g);
  return parts.map((part,i) => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={i}>{part.slice(2,-2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={i}>{part.slice(1,-1)}</code>;
    const match = /^\[([^\]]+)\]\((https:\/\/[^\s)]+)\)$/.exec(part);
    return match ? <a key={i} href={match[2]} target="_blank" rel="noopener noreferrer">{match[1]}</a> : part;
  });
}
export default function RichText({ text }: {text:string}) {
  const lines = text.split(/\r?\n/);
  const blocks: ReactNode[] = [];
  let code: string[]|null = null;
  let list: string[] = [];
  const flushList = (at: number) => { if (list.length) { blocks.push(<ul key={`list-${at}`}>{list.map((x,i)=><li key={i}>{inline(x)}</li>)}</ul>); list=[]; } };
  // Use a normal loop so TypeScript can track the mutable fenced-code state
  // through to the final unfinished-code block below.
  for (const [i, line] of lines.entries()) {
    if (line.startsWith("```")) {
      flushList(i);
      if (code) {
        blocks.push(<pre key={`code-${i}`}><code>{code.join("\n")}</code></pre>);
        code = null;
      } else {
        code = [];
      }
      continue;
    }
    if (code) { code.push(line); continue; }
    if (/^\s*[-*] /.test(line)) { list.push(line.replace(/^\s*[-*] /, "")); continue; }
    flushList(i);
    if (!line.trim()) continue;
    const h = /^(#{1,3})\s+(.+)$/.exec(line);
    if (h) {
      blocks.push(h[1].length <= 2 ? <h2 key={i}>{inline(h[2])}</h2> : <h3 key={i}>{inline(h[2])}</h3>);
      continue;
    }
    if (line.startsWith("> ")) { blocks.push(<blockquote key={i}>{inline(line.slice(2))}</blockquote>); continue; }
    blocks.push(<p key={i}>{inline(line)}</p>);
  }
  flushList(lines.length);
  if(code) blocks.push(<pre key="unfinished-code"><code>{code.join("\n")}</code></pre>);
  return <div className={s.markdown}>{blocks}</div>;
}
