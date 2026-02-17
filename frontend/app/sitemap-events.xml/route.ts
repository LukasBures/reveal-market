import type { MetadataRoute } from "next";
import { DEFAULT_API_BASE } from "@/lib/api";
import { resolveUrlConfig } from "@/lib/env-presets";

export const revalidate = 3600;

const EVENT_PAGE_SIZE = 10000;
const EVENT_ORDER_BY = "volume";

const buildEventPath = (eventId: string): string => `/events/${encodeURIComponent(eventId)}`;

const extractEventId = (item: any): string | null => {
  const candidate =
    item?.group_slug ??
    item?.groupSlug ??
    item?.event_key ??
    item?.eventKey ??
    item?.event_id ??
    item?.eventId;
  if (typeof candidate !== "string") {
    return null;
  }
  const trimmed = candidate.trim();
  if (!trimmed || trimmed === "unknown") {
    return null;
  }
  return trimmed;
};

const extractLastModified = (item: any): string | undefined => {
  const candidate =
    item?.updated_at ??
    item?.updatedAt ??
    item?.extra_data?.updated_at ??
    item?.extraData?.updatedAt ??
    item?.extra_data?.gamma?.updated_at ??
    item?.extraData?.gamma?.updatedAt;
  return typeof candidate === "string" && candidate.trim() ? candidate : undefined;
};

export default async function sitemap(request: Request): Promise<MetadataRoute.Sitemap> {
  const { siteUrl, apiBaseInternal } = resolveUrlConfig();
  const apiBase = (apiBaseInternal || DEFAULT_API_BASE).replace(/\/$/, "");
  const now = new Date().toISOString();
  const entries: MetadataRoute.Sitemap = [];
  const seen = new Set<string>();

  const url = new URL(request.url);
  const pageParam = Number(url.searchParams.get("page") ?? "1");
  const page = Number.isFinite(pageParam) && pageParam > 0 ? Math.floor(pageParam) : 1;
  const offset = (page - 1) * EVENT_PAGE_SIZE;

  const params = new URLSearchParams();
  params.set("limit", String(EVENT_PAGE_SIZE));
  params.set("status", "any");
  params.set("order_by", EVENT_ORDER_BY);
  params.set("coalesce_groups", "1");
  params.set("offset", String(offset));

  const endpoint = new URL("/events", apiBase);
  params.forEach((value, key) => endpoint.searchParams.set(key, value));

  const response = await fetch(endpoint.toString(), {
    cache: "force-cache",
    next: { revalidate },
  });

  if (!response.ok) {
    return entries;
  }

  const payload = await response.json();
  const data = Array.isArray(payload) ? payload : payload?.items ?? [];
  if (!Array.isArray(data) || data.length === 0) {
    return entries;
  }

  for (const item of data) {
    const eventId = extractEventId(item);
    if (!eventId || seen.has(eventId)) {
      continue;
    }
    seen.add(eventId);
    entries.push({
      url: `${siteUrl}${buildEventPath(eventId)}`,
      lastModified: extractLastModified(item) ?? now,
      changeFrequency: "daily",
      priority: 0.55,
    });
  }

  return entries;
}
