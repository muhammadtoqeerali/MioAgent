import { NextRequest, NextResponse } from "next/server";
export const dynamic = "force-dynamic";
export async function GET(req: NextRequest, context: {params: Promise<{id:string}>}) {
  if(process.env.VERCEL === "1")return NextResponse.json({detail:"Local images unavailable on remote hosting"},{status:503});
  const {id}=await context.params;
  if(!/^[0-9a-f]{32}$/.test(id))return NextResponse.json({detail:"Invalid image"},{status:404});
  if(process.env.MIO_API_URL!=="http://127.0.0.1:8000"||!process.env.MIO_API_TOKEN)
    return NextResponse.json({detail:"Private backend not configured"},{status:503});
  try{
    const r=await fetch(`http://127.0.0.1:8000/api/omni/images/${id}/file`,{
      headers:{Authorization:`Bearer ${process.env.MIO_API_TOKEN}`},
      cache:"no-store",redirect:"manual",signal:AbortSignal.timeout(15000)});
    if(!r.ok)return NextResponse.json({detail:"Image unavailable"},{status:r.status});
    if(!(r.headers.get("content-type")||"").startsWith("image/png"))throw new Error("Invalid MIME type");
    const body=await r.arrayBuffer();if(body.byteLength>8*1024*1024)throw new Error("Oversized image");
    const download=req.nextUrl.searchParams.get("download")==="1";
    return new NextResponse(body,{status:200,headers:{"Content-Type":"image/png","Cache-Control":"private, no-store",
      "X-Content-Type-Options":"nosniff",
      ...(download?{"Content-Disposition":`attachment; filename="mioagent-${id}.png"`}:{})}});
  }catch{return NextResponse.json({detail:"Image backend unavailable"},{status:502});}
}
