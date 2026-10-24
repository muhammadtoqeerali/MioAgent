import type { Metadata } from "next";
import "./globals.css";
import "./_mio/scorpio8a.css";
import "./_mio/scorpio8c.css";
import ScorpioShell from "./_mio/scorpio8a-shell";

export const metadata: Metadata = {
  title: "Scorpio | AI Agent Control Room",
  description: "Scorpio local-first AI workspace, Chat, Projects, Work and owner-controlled approvals",
};
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body><ScorpioShell>{children}</ScorpioShell></body></html>;
}
