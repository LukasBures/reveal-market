"use server";

import type { FetchFeaturedMarketsOptions } from "@/lib/api-types";
import { fetchFeaturedEvents } from "@/lib/api";

export async function loadFeaturedEventsAction(limit: number, options?: FetchFeaturedMarketsOptions) {
  return fetchFeaturedEvents(limit, options);
}
