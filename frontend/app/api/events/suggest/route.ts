import { NextResponse } from "next/server";

import { DEFAULT_API_BASE } from "@/lib/api";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const params = url.searchParams;
  const q = params.get("q") ?? "";
  const limit = params.get("limit") ?? "5";
  const endpoint = new URL("/events/suggest", DEFAULT_API_BASE);
  endpoint.searchParams.set("q", q);
  endpoint.searchParams.set("limit", limit);
  const response = await fetch(endpoint.toString(), { cache: "no-store" });
  if (!response.ok) {
    return NextResponse.json([], { status: response.status });
  }
  const payload = await response.json();
  return NextResponse.json(payload);
}
