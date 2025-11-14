import { NextResponse } from "next/server";

import { fetchFeaturedMarkets } from "@/lib/api";
import { DEFAULT_PAGE_SIZE } from "@/components/markets/constants";

const MAX_LIMIT = 100;

export async function GET(request: Request) {
  const url = new URL(request.url);
  const params = url.searchParams;
  const parsedLimit = Number(params.get("limit"));
  const limit = Number.isFinite(parsedLimit) ? Math.min(Math.max(parsedLimit, 1), MAX_LIMIT) : DEFAULT_PAGE_SIZE;
  const parsedOffset = Number(params.get("offset"));
  const offset = Number.isFinite(parsedOffset) && parsedOffset > 0 ? parsedOffset : undefined;
  const searchQuery = params.get("search") ?? undefined;
  const category = params.get("category") ?? undefined;

  const markets = await fetchFeaturedMarkets(limit, {
    searchQuery,
    category,
    offset,
  });

  return NextResponse.json(markets);
}
