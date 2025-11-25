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
import { getServerEnv } from "./serverEnv";

export const DEFAULT_API_BASE = getServerEnv().apiBaseUrl;

const DEFAULT_REVALIDATE_SECONDS = 30;
const DEFAULT_SUGGEST_REVALIDATE_SECONDS = 15;
const FORCE_OFFLINE = process.env.RM_FORCE_OFFLINE === "true";

const normalizeBase = (value: string) => {
  try {
    return new URL(value).toString().replace(/\/$/, "");
  } catch {
    return value.replace(/\/$/, "");
  }
};

const OFFLINE_FALLBACK_BASE = process.env.RM_OFFLINE_API_BASE_URL
  ? normalizeBase(process.env.RM_OFFLINE_API_BASE_URL)
  : null;
const API_BASE_NORMALIZED = normalizeBase(DEFAULT_API_BASE);
const IS_OFFLINE_BASE = OFFLINE_FALLBACK_BASE ? API_BASE_NORMALIZED === OFFLINE_FALLBACK_BASE : false;
const SHOULD_SKIP_NETWORK = FORCE_OFFLINE && IS_OFFLINE_BASE;

const isNetworkUnavailable = (error: unknown) => {
  const message = error instanceof Error ? error.message.toLowerCase() : String(error ?? "").toLowerCase();
  return (
    message.includes("fetch failed") ||
    message.includes("econnrefused") ||
    message.includes("enotfound") ||
    message.includes("timed out")
  );
};

const logOfflineAwareError = (scope: string, error: unknown, meta?: Record<string, unknown>) => {
  const message = error instanceof Error ? error.message : String(error ?? "unknown");
  const payload = meta ? { ...meta, error: message } : { error: message };
  if (IS_OFFLINE_BASE && isNetworkUnavailable(error)) {
    logger.debug(`${scope}:offline`, { baseUrl: DEFAULT_API_BASE, ...payload });
    return;
  }
  logger.error(`${scope}:error`, payload);
};

const maybeShortCircuitOffline = (scope: string) => {
  if (SHOULD_SKIP_NETWORK) {
    logger.debug(`${scope}:offline_skip`, { baseUrl: DEFAULT_API_BASE });
    return true;
  }
  return false;
};

export async function fetchFeaturedMarkets(limit = 6, options?: FetchFeaturedMarketsOptions): Promise<MarketSummary[]> {
  if (maybeShortCircuitOffline("fetchFeaturedMarkets")) {
    return [];
  }
  try {
    let endpoint = "/markets";
    const params = new URLSearchParams();
    params.set("limit", String(limit));
    if (typeof options?.offset === "number") {
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
    logger.debug("fetchFeaturedMarkets:request", {
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
    logger.debug("fetchFeaturedMarkets:success", {
      limit,
      category: options?.category,
      searchQuery: options?.searchQuery,
      count: items.length,
      cacheTags: fetchTags,
    });
    return items.map(mapApiMarketToSummary);
  } catch (error) {
    logOfflineAwareError("fetchFeaturedMarkets", error);
    return [];
  }
}

export async function fetchMarketSuggestions(
  query: string,
  limit = 5,
  options?: { revalidate?: number },
): Promise<MarketSummary[]> {
  if (maybeShortCircuitOffline("fetchMarketSuggestions")) {
    return [];
  }
  const trimmed = query.trim();
  if (trimmed.length < 2) {
    return [];
  }
  const normalized = trimmed.toLowerCase();
  const url = new URL("/markets/suggest", DEFAULT_API_BASE);
  url.searchParams.set("limit", String(limit));
  url.searchParams.set("q", trimmed);

  try {
    logger.debug("fetchMarketSuggestions:request", {
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
    logger.debug("fetchMarketSuggestions:success", { query: trimmed, count: mapped.length });
    return mapped;
  } catch (error) {
    logOfflineAwareError("fetchMarketSuggestions", error);
    return [];
  }
}

export async function fetchMarketStatsBreakdown(): Promise<MarketStatusStat[]> {
  if (maybeShortCircuitOffline("fetchMarketStatsBreakdown")) {
    return [];
  }
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

    const normalized = payload.reduce<Record<string, number>>((acc, item) => {
      const key = String(item?.status ?? "unknown").toLowerCase();
      const count = Number(item?.count ?? 0);
      acc[key] = (acc[key] ?? 0) + (Number.isFinite(count) ? count : 0);
      return acc;
    }, {});
    const live = normalized["live"] ?? 0;
    const finalized = normalized["finalized"] ?? 0;
    const total = normalized["total"] ?? live + finalized;
    const stats: MarketStatusStat[] = [
      { status: "live", count: live },
      { status: "finalized", count: finalized },
      { status: "total", count: total },
    ];
    logger.debug("fetchMarketStatsBreakdown:success", { count: stats.length });
    return stats;
  } catch (error) {
    logOfflineAwareError("fetchMarketStatsBreakdown", error);
    return [];
  }
}

export async function fetchHealthSnapshot(): Promise<HealthSnapshot | null> {
  if (maybeShortCircuitOffline("fetchHealthSnapshot")) {
    return null;
  }
  const endpoint = `${DEFAULT_API_BASE}/healthz`;
  try {
    logger.debug("fetchHealthSnapshot:request", { endpoint, baseUrl: DEFAULT_API_BASE });
    const response = await fetch(endpoint, {
      next: { revalidate: 45 },
    });
    if (!response.ok) {
      // Advisory only; skip logging for 404/503 to avoid noise.
      if (response.status === 404 || response.status === 503) {
        return null;
      }
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
    logger.debug("fetchHealthSnapshot:success", {
      status: snapshot.status,
      endpoint,
    });
    return snapshot;
  } catch (error) {
    logOfflineAwareError("fetchHealthSnapshot", error);
    return null;
  }
}

export async function fetchProofReceipts(
  limit = 20,
  options?: { offset?: number },
): Promise<{ receipts: ProofReceipt[]; error?: string }> {
  if (maybeShortCircuitOffline("fetchProofReceipts")) {
    return { receipts: [], error: "offline" };
  }
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
      const errorMessage = `Failed to fetch proof receipts (${response.status})`;
      logger.error("fetchProofReceipts:failed", { status: response.status, endpoint, offset });
      return { receipts: [], error: errorMessage };
    }
    const payload = await response.json();
    if (Array.isArray(payload)) {
      logger.info("fetchProofReceipts:success", { count: payload.length, offset });
      return { receipts: payload as ProofReceipt[] };
    }
    if (payload?.data && Array.isArray(payload.data)) {
      logger.info("fetchProofReceipts:success", { count: payload.data.length, offset });
      return { receipts: payload.data as ProofReceipt[] };
    }
    return { receipts: [] };
  } catch (error) {
    logOfflineAwareError("fetchProofReceipts", error, { offset });
    return { receipts: [], error: (error as Error).message };
  }
}

export async function fetchInvestorKpis(): Promise<InvestorKpis> {
  const [statsResult, healthResult] = await Promise.allSettled([
    fetchMarketStatsBreakdown(),
    fetchHealthSnapshot(),
  ]);

  const stats = statsResult.status === "fulfilled" ? statsResult.value : [];
  const health = healthResult.status === "fulfilled" ? healthResult.value : null;

  const liveStat = stats.find((item) => item.status === "live")?.count ?? 0;
  const finalizedStat = stats.find((item) => item.status === "finalized")?.count ?? 0;
  const snapshot = {
    openMarkets: liveStat,
    settledMarkets: finalizedStat,
    databaseLatencyMs: health?.databaseLatencyMs ?? null,
    lastUpdatedIso: health?.timestamp ?? null,
  };
  logger.debug("fetchInvestorKpis:computed", snapshot);
  return snapshot;
}

export async function fetchMarketByEventId(eventId: string): Promise<MarketDetail | null> {
  if (maybeShortCircuitOffline("fetchMarketByEventId")) {
    return null;
  }
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
      umaStatus: payload.uma_resolution_status ?? undefined,
      marketAddress: payload.market_address ?? undefined,
      rakeBps: payload.rake_bps ?? undefined,
      startsAt: payload.starts_at ?? null,
      closesAt: payload.closes_at ?? payload.commit_deadline ?? null,
      ordersOpenedAt: payload.orders_opened_at ?? null,
      resolutionSource: payload.resolution_source ?? undefined,
      marketMaker: payload.market_maker ?? undefined,
      orderMinSize: payload.order_min_size ?? undefined,
      priceTickSize: payload.price_tick_size ?? undefined,
      enableOrderBook:
        typeof payload.enable_order_book === "boolean" ? payload.enable_order_book : undefined,
      clobTokenIds: payload.clob_token_ids ?? undefined,
      imageVariants: payload.image_variants ?? undefined,
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
    logOfflineAwareError("fetchMarketByEventId", error, { eventId });
    return null;
  }
}
