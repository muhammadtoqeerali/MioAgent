import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export async function POST(req: NextRequest) {
  if (process.env.VERCEL === "1") {
    return NextResponse.json({ detail: "Remote controls require a secure private connection" }, { status: 503 });
  }
  const origin = req.headers.get("origin");
  const host = req.headers.get("host");
  try {
    if (!origin || !host || new URL(origin).host !== host) throw new Error("invalid origin");
  } catch {
    return NextResponse.json({ detail: "Cross-origin request denied" }, { status: 403 });
  }
  const token = process.env.MIO_API_TOKEN;
  if (!token || process.env.MIO_API_URL !== "http://127.0.0.1:8000") {
    return NextResponse.json({ detail: "Private backend unavailable" }, { status: 503 });
  }
  try {
    const data = await req.text();
    if (data.length > 37000) return NextResponse.json({ detail: "Request too large" }, { status: 413 });
    const result = await fetch("http://127.0.0.1:8000/api/studio/respond", {
      method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: data, cache: "no-store", redirect: "manual", signal: AbortSignal.timeout(235000),
    });
    return new NextResponse(await result.text(), { status: result.status,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ detail: "Local assistant timed out or is offline" }, { status: 502 });
  }
}
