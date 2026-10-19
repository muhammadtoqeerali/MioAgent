import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export async function GET(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  if (process.env.VERCEL === "1") return NextResponse.json({ detail: "Local only" }, { status: 503 });
  const id = (await ctx.params).id;
  if (!/^[0-9a-f]{32}$/.test(id)) return NextResponse.json({ detail: "Not found" }, { status: 404 });
  const token = process.env.MIO_API_TOKEN;
  if (!token || process.env.MIO_API_URL !== "http://127.0.0.1:8000") {
    return NextResponse.json({ detail: "Private backend unavailable" }, { status: 503 });
  }
  try {
    const result = await fetch(`http://127.0.0.1:8000/api/studio/images/${id}/file`, {
      headers: { Authorization: `Bearer ${token}` }, cache: "no-store",
      redirect: "manual", signal: AbortSignal.timeout(30000),
    });
    if (!result.ok) return NextResponse.json({ detail: "Image not available" }, { status: 404 });
    const bytes = await result.arrayBuffer();
    if (bytes.byteLength > 8 * 1024 * 1024) return NextResponse.json({ detail: "Image too large" }, { status: 413 });
    return new NextResponse(bytes, { status: 200,
      headers: { "Content-Type": "image/png", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" } });
  } catch {
    return NextResponse.json({ detail: "Image backend offline" }, { status: 502 });
  }
}
