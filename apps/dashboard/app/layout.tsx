import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "MioAgent | Command Center",
  description: "MioAgent workstation control center — Phase 1 foundation",
};
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
