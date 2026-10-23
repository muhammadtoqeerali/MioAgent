import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "Scorpio | AI Control Room",
  description: "Scorpio local-first AI control room and owner-reviewed Work dashboard",
};
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
