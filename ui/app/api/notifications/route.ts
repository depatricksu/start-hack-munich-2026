import { NextResponse } from "next/server";
import { getNotifications } from "@/lib/notifications";

export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json({ notifications: getNotifications() });
}
