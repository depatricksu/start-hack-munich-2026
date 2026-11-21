import { NextResponse } from "next/server";
import { getDetail } from "@/lib/data";

export const dynamic = "force-dynamic";

export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  return NextResponse.json(getDetail(Number(id)));
}
