import { NextResponse } from "next/server";
import { getCarrierFlags, getInvoices } from "@/lib/invoices";

export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json({ invoices: getInvoices(), carriers: getCarrierFlags() });
}
