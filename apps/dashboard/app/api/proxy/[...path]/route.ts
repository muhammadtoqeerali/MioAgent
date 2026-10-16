import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

async function forward(req: NextRequest, path: string[]) {
  if (req.method !== "GET" && req.method !== "HEAD") {
    const origin = req.headers.get("origin");
    const host = req.headers.get("host");
    let validOrigin = false;
    try { validOrigin = !!origin && !!host && new URL(origin).host === host; }
    catch { validOrigin = false; }
    if (!validOrigin) {
      return NextResponse.json({ detail: "Cross-origin mutations denied" }, { status: 403 });
    }
  }
  const apiBase = process.env.MIO_API_URL;
  const token = process.env.MIO_API_TOKEN;
  if (!apiBase || !token) {
    return NextResponse.json({ detail: "Server API settings are missing" }, { status: 503 });
  }
  const safePath = path.map((piece) => encodeURIComponent(piece)).join("/");
  const target = `${apiBase.replace(/\/$/, "")}/api/${safePath}${req.nextUrl.search}`;
  try {
    const response = await fetch(target, {
      method: req.method,
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: req.method === "GET" || req.method === "HEAD" ? undefined : await req.text(),
      cache: "no-store",
      signal: AbortSignal.timeout(15000),
    });
    return new NextResponse(await response.text(), {
      status: response.status,
      headers: { "Content-Type": response.headers.get("Content-Type") ?? "application/json",
                 "Cache-Control": "no-store" },
    });
  } catch {
    return NextResponse.json({ detail: "MioAgent API unavailable" }, { status: 502 });
  }
}

type Context = { params: Promise<{ path: string[] }> };
export async function GET(req: NextRequest, ctx: Context) {
  return forward(req, (await ctx.params).path);
}
export async function POST(req: NextRequest, ctx: Context) {
  return forward(req, (await ctx.params).path);
}

export async function DELETE(req: NextRequest, ctx: Context) {
  return forward(req, (await ctx.params).path);
}
