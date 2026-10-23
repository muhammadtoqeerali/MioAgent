"use client";
import type { ReactNode } from "react";
import s from "./experience.module.css";

type Section = "chat" | "projects" | "work";
const navigation = [
  { id: "chat", label: "Chat", icon: "◇", href: "/chat" },
  { id: "projects", label: "Projects", icon: "▦", href: "/projects-space" },
  { id: "work", label: "Work", icon: "✳", href: "/work-mode" },
] as const;

export default function UIShell({ section, title, subtitle, children, sidebarContent }:{
  section: Section; title: string; subtitle: string; children: ReactNode; sidebarContent?: ReactNode;
}) {
  return <div className={s.shell}>
    <aside className={s.sidebar} aria-label="Main navigation">
      <a href="/control-room" className={s.brand}><img src="/scorpio-mark.svg" alt="" width={34} height={34}/>Scorpio</a>
      {navigation.map(item => <a key={item.id} href={item.href} className={`${s.navItem} ${item.id === section ? s.navActive : ""}`} aria-current={item.id === section ? "page" : undefined}><span aria-hidden className={s.navIcon}>{item.icon}</span>{item.label}</a>)}
      <div className={s.sideDivider} />
      <a href="/control-room" className={s.navItem}><span aria-hidden className={s.navIcon}>▥</span>Control Room ↗</a>
      {sidebarContent && <><div className={s.sideDivider}/><div className={s.sideSlot}>{sidebarContent}</div></>}
      <div className={s.sideFooter}>Private workstation · Local models<br/>Scorpio · Local platform</div>
    </aside>
    <main className={s.main}>
      <header className={s.header}><div><h1>{title}</h1><p>{subtitle}</p></div><span className={s.online}>● Local-first</span></header>
      {children}
    </main>
  </div>;
}
