"use client";
import type { ReactNode } from "react";
import s from "./experience.module.css";

// ScorpioShell owns global navigation across all routes. UIShell provides only
// the inner application workspace and optional chat-history context sidebar.
type Section = "chat" | "projects" | "work";
const navigation = ["/chat", "/projects-space", "/work-mode", "/control-room"] as const;
export default function UIShell({ section, title, subtitle, children, sidebarContent }: {
  section: Section; title: string; subtitle: string; children: ReactNode; sidebarContent?: ReactNode;
}) {
  return <div className={s.shell} data-scorpio-section={section} data-scorpio-navigation={navigation.join(",")}>
    {sidebarContent && <aside className={s.sidebar} aria-label="Conversation history">
      <div className={s.sideCaption}>CHAT HISTORY</div>
      <div className={s.sideSlot}>{sidebarContent}</div>
    </aside>}
    <main className={s.main}>
      <header className={s.header}><div><h1>{title}</h1><p>{subtitle}</p></div><span className={s.online}>● Local workspace</span></header>
      {children}
    </main>
  </div>;
}
