import { NextResponse } from "next/server";

import { DEFAULT_API_BASE } from "@/lib/api";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const params = url.searchParams;
  const q = (params.get("q") ?? "").trim();
  if (q.length < 2) {
    return NextResponse.json([], { status: 200 });
  }
  if (q.length > 200) {
    return NextResponse.json({ error: "query_too_long" }, { status: 400 });
  }
  const parsedLimit = Number.parseInt(params.get("limit") ?? "5", 10);
  const limit = Number.isFinite(parsedLimit)
    ? String(Math.min(Math.max(parsedLimit, 1), 50))
    : "5";
  const endpoint = new URL("/events/suggest", DEFAULT_API_BASE);
  endpoint.searchParams.set("q", q);
  endpoint.searchParams.set("limit", limit);
  const response = await fetch(endpoint.toString(), {
    next: { revalidate: 15 },
  });
  if (!response.ok) {
    return NextResponse.json([], { status: response.status });
  }
  const payload = await response.json();
  return NextResponse.json(payload, {
    headers: {
      "Cache-Control": "public, s-maxage=15, stale-while-revalidate=30",
    },
  });
}
