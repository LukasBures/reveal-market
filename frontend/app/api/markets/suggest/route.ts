import { NextResponse } from "next/server";

import { fetchMarketSuggestions } from "@/lib/api";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const query = (url.searchParams.get("q") ?? "").trim();
  const parsedLimit = Number(url.searchParams.get("limit"));
  const limit = Number.isFinite(parsedLimit) ? Math.min(Math.max(parsedLimit, 1), 10) : 5;

  const { data: suggestions } = await fetchMarketSuggestions(query, limit);
  return NextResponse.json(suggestions);
}
