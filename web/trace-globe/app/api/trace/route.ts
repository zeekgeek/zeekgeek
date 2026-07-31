import { NextRequest, NextResponse } from "next/server";
import { executeTrace } from "@/lib/traceEngine";
import type { TraceApiResponse } from "@/lib/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 120;

export async function POST(request: NextRequest) {
  try {
    const body = (await request.json()) as { target?: string };
    const target = body.target?.trim();
    if (!target) {
      return NextResponse.json(
        { ok: false, error: "Missing target" } satisfies TraceApiResponse,
        { status: 400 },
      );
    }
    const result = await executeTrace(target);
    if (result.status === "failed") {
      return NextResponse.json(
        { ok: false, error: result.error, result } satisfies TraceApiResponse,
        { status: 422 },
      );
    }
    return NextResponse.json({ ok: true, result } satisfies TraceApiResponse);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Trace failed";
    return NextResponse.json(
      { ok: false, error: message } satisfies TraceApiResponse,
      { status: 500 },
    );
  }
}

export async function GET(request: NextRequest) {
  const target = request.nextUrl.searchParams.get("target");
  if (!target) {
    return NextResponse.json(
      { ok: false, error: "Pass ?target=hostname" } satisfies TraceApiResponse,
      { status: 400 },
    );
  }
  const result = await executeTrace(target);
  if (result.status === "failed") {
    return NextResponse.json(
      { ok: false, error: result.error, result } satisfies TraceApiResponse,
      { status: 422 },
    );
  }
  return NextResponse.json({ ok: true, result } satisfies TraceApiResponse);
}
