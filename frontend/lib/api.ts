import "server-only";

import type {
  FetchFeaturedMarketsOptions,
  HealthSnapshot,
  InvestorKpis,
  MarketDetail,
  MarketStatusStat,
  MarketSummary,
  ProofReceipt,
} from "./api-types";
import { slugify } from "./slugs";
import { logger } from "./logging";
import { mapApiMarketToSummary } from "./marketMapper";

export const DEFAULT_API_BASE =
  process.env.RM_API_BASE_URL ??
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  (process.env.NODE_ENV === "development" ? "http://localhost:8000" : "http://api:8000");

const DEFAULT_REVALIDATE_SECONDS = 30;
const DEFAULT_SUGGEST_REVALIDATE_SECONDS = 15;

export async function fetchFeaturedMarkets(limit = 6, options?: FetchFeaturedMarketsOptions): Promise<MarketSummary[]> {
  try {
    let endpoint = "/markets";
    const params = new URLSearchParams();
    params.set("limit", String(limit));
    if (typeof options?.offset === "number" && !options?.category) {
      params.set("offset", String(options.offset));
    }
    if (options?.searchQuery && !options.category) {
      const trimmedSearch = options.searchQuery.trim();
      if (trimmedSearch.length >= 2) {
        params.set("search", trimmedSearch);
      } else if (trimmedSearch.length > 0) {
        return [];
      }
    }
    const fetchTags: string[] = [];
    if (options?.category) {
      const slug = slugify(options.category);
      endpoint = `/categories/${encodeURIComponent(slug)}`;
      fetchTags.push(`category:${slug}`);
    } else {
      fetchTags.push("markets:list");
    }
    const url = new URL(endpoint, DEFAULT_API_BASE);
    params.forEach((value, key) => url.searchParams.set(key, value));
    logger.info("fetchFeaturedMarkets:request", {
      endpoint: url.toString(),
      limit,
      offset: options?.offset,
      category: options?.category,
      searchQuery: options?.searchQuery,
      revalidate: options?.revalidate ?? DEFAULT_REVALIDATE_SECONDS,
    });
    const response = await fetch(url.toString(), {
      cache: "force-cache",
      next: { revalidate: options?.revalidate ?? DEFAULT_REVALIDATE_SECONDS, tags: fetchTags },
    });

    if (!response.ok) {
      logger.error("fetchFeaturedMarkets:failed", {
        status: response.status,
        endpoint: url.toString(),
        baseUrl: DEFAULT_API_BASE,
      });
      return [];
    }

    const payload = await response.json();
    const items = Array.isArray(payload) ? payload : payload?.items ?? [];
    logger.info("fetchFeaturedMarkets:success", {
      limit,
      category: options?.category,
      searchQuery: options?.searchQuery,
      count: items.length,
      cacheTags: fetchTags,
    });
    return items.map(mapApiMarketToSummary);
  } catch (error) {
    logger.error("fetchFeaturedMarkets:error", { error: (error as Error).message });
    return [];
  }
}

export async function fetchMarketSuggestions(
  query: string,
  limit = 5,
  options?: { revalidate?: number },
): Promise<MarketSummary[]> {
  const trimmed = query.trim();
  if (trimmed.length < 2) {
    return [];
  }
  const normalized = trimmed.toLowerCase();
  const url = new URL("/markets/suggest", DEFAULT_API_BASE);
  url.searchParams.set("limit", String(limit));
  url.searchParams.set("q", trimmed);

  try {
    logger.info("fetchMarketSuggestions:request", {
      endpoint: url.toString(),
      limit,
      query: trimmed,
    });
    const response = await fetch(url.toString(), {
      cache: "force-cache",
      next: {
        revalidate: options?.revalidate ?? DEFAULT_SUGGEST_REVALIDATE_SECONDS,
        tags: [`suggest:${normalized}`],
      },
    });
    if (!response.ok) {
      logger.error("fetchMarketSuggestions:failed", { status: response.status, endpoint: url.toString() });
      return [];
    }
    const payload = await response.json();
    if (!Array.isArray(payload)) {
      return [];
    }
    const mapped = payload.map(mapApiMarketToSummary);
    logger.info("fetchMarketSuggestions:success", { query: trimmed, count: mapped.length });
    return mapped;
  } catch (error) {
    logger.error("fetchMarketSuggestions:error", { error: (error as Error).message });
    return [];
  }
}

export async function fetchMarketStatsBreakdown(): Promise<MarketStatusStat[]> {
  try {
    const response = await fetch(`${DEFAULT_API_BASE}/markets/stats`, {
      next: { revalidate: 60 },
    });

    if (!response.ok) {
      logger.error("fetchMarketStatsBreakdown:failed", { status: response.status });
      return [];
    }

    const payload = await response.json();
    if (!Array.isArray(payload)) {
      return [];
    }

    const stats = payload.map((item) => ({
      status: String(item?.status ?? "unknown").toLowerCase(),
      count: Number(item?.count ?? 0),
    }));
    logger.info("fetchMarketStatsBreakdown:success", { count: stats.length });
    return stats;
  } catch (error) {
    logger.error("fetchMarketStatsBreakdown:error", { error: (error as Error).message });
    return [];
  }
}

export async function fetchHealthSnapshot(): Promise<HealthSnapshot | null> {
  try {
    const endpoint = `${DEFAULT_API_BASE}/health`;
    logger.info("fetchHealthSnapshot:request", { endpoint, baseUrl: DEFAULT_API_BASE });
    const response = await fetch(endpoint, {
      next: { revalidate: 45 },
    });
    if (!response.ok) {
      logger.error("fetchHealthSnapshot:failed", { status: response.status, endpoint, baseUrl: DEFAULT_API_BASE });
      return null;
    }
    const payload = await response.json();
    const components = payload?.components ?? {};
    const snapshot: HealthSnapshot = {
      status: String(payload?.status ?? "unknown"),
      timestamp: payload?.timestamp,
      databaseLatencyMs: components?.database?.latency_ms ?? components?.database?.latencyMs ?? null,
      redisLatencyMs: components?.redis?.latency_ms ?? components?.redis?.latencyMs ?? null,
      workerHeartbeat: components?.worker
        ? {
            marketsProcessed: components.worker.detail
              ? parseInt(components.worker.detail.replace(/[^\d]/g, ""), 10) || undefined
              : undefined,
            latencyMs: components.worker.latency_ms ?? null,
            timestamp: payload?.timestamp,
          }
        : null,
    };
    logger.info("fetchHealthSnapshot:success", {
      status: snapshot.status,
    });
    return snapshot;
  } catch (error) {
    logger.error("fetchHealthSnapshot:error", { error: (error as Error).message });
    return null;
  }
}

export async function fetchProofReceipts(
  limit = 20,
  options?: { offset?: number },
): Promise<ProofReceipt[]> {
  const offset = Math.max(0, options?.offset ?? 0);

  const url = new URL(`${DEFAULT_API_BASE}/proofs`);
  url.searchParams.set("limit", `${limit}`);
  if (offset > 0) {
    url.searchParams.set("offset", `${offset}`);
  }

  try {
    const endpoint = url.toString();
    logger.info("fetchProofReceipts:request", { endpoint, limit, offset, baseUrl: DEFAULT_API_BASE });
    const response = await fetch(endpoint, {
      next: { revalidate: DEFAULT_REVALIDATE_SECONDS },
    });
    if (!response.ok) {
      throw new Error(`Failed to fetch proof receipts (${response.status})`);
    }
    const payload = await response.json();
    if (Array.isArray(payload)) {
      logger.info("fetchProofReceipts:success", { count: payload.length, offset });
      return payload as ProofReceipt[];
    }
    if (payload?.data && Array.isArray(payload.data)) {
      logger.info("fetchProofReceipts:success", { count: payload.data.length, offset });
      return payload.data as ProofReceipt[];
    }
    return [];
  } catch (error) {
    logger.error("fetchProofReceipts:error", { error: (error as Error).message, offset });
    return [];
  }
}

export async function fetchInvestorKpis(): Promise<InvestorKpis> {
  const [statsResult, healthResult] = await Promise.allSettled([
    fetchMarketStatsBreakdown(),
    fetchHealthSnapshot(),
  ]);

  const stats = statsResult.status === "fulfilled" ? statsResult.value : [];
  const health = healthResult.status === "fulfilled" ? healthResult.value : null;

  const openMarkets = stats
    .filter((item) => ["commit", "locked"].includes(item.status))
    .reduce((total, item) => total + item.count, 0);

  const settledMarkets = stats
    .filter((item) => item.status === "settled")
    .reduce((total, item) => total + item.count, 0);
  const snapshot = {
    openMarkets,
    settledMarkets,
    databaseLatencyMs: health?.databaseLatencyMs ?? null,
    lastUpdatedIso: health?.timestamp ?? null,
  };
  logger.debug("fetchInvestorKpis:computed", snapshot);
  return snapshot;
}

export async function fetchMarketByEventId(eventId: string): Promise<MarketDetail | null> {
  try {
    const detailUrl = `${DEFAULT_API_BASE}/markets/${eventId}`;
    logger.info("fetchMarketByEventId:request", { eventId, endpoint: detailUrl });
    const response = await fetch(detailUrl, {
      next: { revalidate: 30 },
    });
    if (response.status === 404) {
      logger.warn("fetchMarketByEventId:not_found", { eventId });
      return null;
    }
    if (!response.ok) {
      logger.error("fetchMarketByEventId:failed", {
        eventId,
        status: response.status,
        endpoint: detailUrl,
        baseUrl: DEFAULT_API_BASE,
      });
      return null;
    }
    const payload = await response.json();
    const resolutionSource = payload.extra_data?.resolution;
    const detail: MarketDetail = {
      eventId: payload.event_id ?? eventId,
      title: payload.title ?? "Untitled market",
      category: payload.category ?? undefined,
      tags: payload.tags ?? payload.extra_data?.tags ?? [],
      status: payload.status ?? undefined,
      commitDeadline: payload.commit_deadline ?? undefined,
      revealDeadline: payload.reveal_deadline ?? undefined,
      liquidityUsd: payload.extra_data?.liquidity_usd ?? undefined,
      outcomes: payload.outcomes ?? [],
      outcomePrices: payload.outcome_prices ?? [],
      imageUrl:
        payload.image_url ??
        payload.extra_data?.image_url ??
        payload.extra_data?.gamma?.image_url ??
        payload.extra_data?.gamma?.imageUrl ??
        null,
      slug: payload.slug ?? payload.extra_data?.gamma?.slug,
      factory: payload.factory ?? undefined,
      conditionId: payload.condition_id ?? undefined,
      questionId: payload.question_id ?? undefined,
      umaStatus: payload.uma_resolution_status ?? undefined,
      marketAddress: payload.market_address ?? undefined,
      rakeBps: payload.rake_bps ?? undefined,
      resolution: resolutionSource
        ? {
            resolved: Boolean(resolutionSource.resolved),
            payouts: resolutionSource.payouts ?? [],
            winners: resolutionSource.winners ?? [],
            checkedAt: resolutionSource.checkedAt,
            blockNumber: resolutionSource.blockNumber,
            transactionHash: resolutionSource.transactionHash,
          }
        : undefined,
      heartbeat: payload.extra_data?.heartbeat
        ? {
            timestamp: payload.extra_data.heartbeat.timestamp,
            latencyMs: payload.extra_data.heartbeat.latency_ms ?? payload.extra_data.heartbeat.latencyMs,
          }
        : undefined,
      description: payload.description ?? payload.extra_data?.description ?? payload.extra_data?.gamma?.description,
      oracle: payload.oracle,
      createdAt: payload.created_at,
      updatedAt: payload.updated_at,
      extraData: payload.extra_data ?? null,
    };
    logger.info("fetchMarketByEventId:success", { eventId });
    return detail;
  } catch (error) {
    logger.error("fetchMarketByEventId:error", { eventId, error: (error as Error).message });
    return null;
  }
}
