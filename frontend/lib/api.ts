import type {
  FetchFeaturedMarketsOptions,
  HealthSnapshot,
  InvestorKpis,
  GroupedMarkets,
  MarketDetail,
  MarketSibling,
  MarketStatusStat,
  MarketSummary,
  ProofReceipt,
} from "./api-types";
import { slugify } from "./slugs";
import { logger } from "./logging";
import { mapApiMarketToSummary } from "./marketMapper";
import { getServerEnv } from "./serverEnv";
import { getMarketVolume } from "./markets";
import { fetchMarketActivity, fetchMarketTokens, fetchOpenInterest, fetchOrderbookAggregates } from "./streamer-data";

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

const computePopularity = (market: MarketSummary): number => {
  const volume = getMarketVolume(market);
  return Number.isFinite(volume) ? volume : 0;
};

const coerceNumber = (value: any): number | undefined => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
};

const coerceId = (value: any, fallback?: string): string => {
  const raw = value ?? fallback ?? "";
  return typeof raw === "string" ? raw.trim() : String(raw);
};

const normalizeClobTokenIds = (value: any): string[] | undefined => {
  if (Array.isArray(value)) return value.map((v) => String(v));
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) return parsed.map((v) => String(v));
    } catch {
      const parts = value.split(",").map((v) => v.trim()).filter(Boolean);
      if (parts.length) return parts;
    }
  }
  return undefined;
};

const mapMarketDetailPayload = (payload: any, eventId: string): MarketDetail => {
  const eventIdValue = coerceId(payload.event_id ?? payload.eventId, eventId);
  const resolutionSource = payload.resolution ?? payload.extra_data?.resolution;
  const groupSlug = payload.group_slug ?? payload.groupSlug ?? payload.extra_data?.group_slug ?? null;
  const groupItemTitle = payload.group_item_title ?? payload.groupItemTitle ?? payload.extra_data?.group_item_title ?? null;
  const groupItemThreshold =
    coerceNumber(payload.group_item_threshold ?? payload.groupItemThreshold ?? payload.extra_data?.group_item_threshold) ??
    null;
  const groupPosition = coerceNumber(payload.group_position ?? payload.groupPosition) ?? null;
  const siblings = Array.isArray(payload.siblings)
    ? payload.siblings
        .map((sibling: any) => {
          const siblingThreshold = coerceNumber(
            sibling.group_item_threshold ?? sibling.groupItemThreshold ?? sibling.groupItemThresh ?? undefined,
          );
          const siblingPosition = coerceNumber(sibling.group_position ?? sibling.groupPosition);
          const siblingCommitDeadline =
            sibling.commit_deadline ??
            sibling.commitDeadline ??
            sibling.closes_at ??
            sibling.closesAt ??
            sibling.orders_opened_at ??
            sibling.ordersOpenedAt ??
            sibling.extra_data?.commit_deadline ??
            sibling.extra_data?.gamma?.commit_deadline ??
            sibling.extra_data?.gamma?.commitDeadline ??
            null;
          const siblingStartsAt =
            sibling.starts_at ?? sibling.startsAt ?? sibling.extra_data?.starts_at ?? sibling.extra_data?.gamma?.starts_at ?? null;
          const siblingClosesAt =
            sibling.closes_at ?? sibling.closesAt ?? sibling.extra_data?.closes_at ?? sibling.extra_data?.gamma?.closes_at ?? null;
          const siblingVolume24h =
            coerceNumber(sibling.volume_24h_usd ?? sibling.volume24hUsd ?? sibling.volume_24h ?? sibling.volume24h) ?? null;
          const siblingVolume =
            coerceNumber(
              sibling.volume ??
                sibling.volume_usd ??
                sibling.extra_data?.volume ??
                sibling.extra_data?.gamma?.volume ??
                sibling.extra_data?.gamma?.volume_num ??
                sibling.extra_data?.gamma?.volumeNum,
            ) ?? null;
          return {
            eventId: coerceId(sibling.event_id ?? sibling.eventId ?? ""),
            title: sibling.title ?? undefined,
            status: sibling.status ?? sibling.extra_data?.status ?? undefined,
            groupItemTitle: sibling.group_item_title ?? sibling.groupItemTitle ?? null,
            groupItemThreshold: siblingThreshold ?? null,
            groupPosition: siblingPosition ?? null,
            outcomePrices: sibling.outcome_prices ?? sibling.outcomePrices ?? undefined,
            volume: siblingVolume,
            volume24hUsd: siblingVolume24h,
            liquidityUsd: coerceNumber(sibling.liquidity_usd ?? sibling.liquidityUsd) ?? null,
            commitDeadline: siblingCommitDeadline,
            startsAt: siblingStartsAt,
            closesAt: siblingClosesAt,
          };
        })
        .filter((sib: MarketSibling) => Boolean(sib.eventId))
    : undefined;
  const bestBid = coerceNumber(
    payload.best_bid ??
      payload.bestBid ??
      payload.extra_data?.gamma?.best_bid ??
      payload.extra_data?.gamma?.bestBid ??
      payload.extra_data?.best_bid ??
      payload.extra_data?.bestBid,
  );
  const bestAsk = coerceNumber(
    payload.best_ask ??
      payload.bestAsk ??
      payload.extra_data?.gamma?.best_ask ??
      payload.extra_data?.gamma?.bestAsk ??
      payload.extra_data?.best_ask ??
      payload.extra_data?.bestAsk,
  );
  const spread = coerceNumber(
    payload.spread ??
      payload.extra_data?.gamma?.spread ??
      payload.extra_data?.spread ??
      (bestBid !== undefined && bestAsk !== undefined ? bestAsk - bestBid : undefined),
  );
  const volume = coerceNumber(
    payload.volume ??
      payload.extra_data?.gamma?.volume ??
      payload.extra_data?.volume ??
      payload.extra_data?.gamma?.volume_num ??
      payload.extra_data?.gamma?.volumeNum,
  );
  const openInterest = coerceNumber(
    payload.open_interest ??
      payload.openInterest ??
      payload.extra_data?.gamma?.open_interest ??
      payload.extra_data?.gamma?.openInterest ??
      payload.extra_data?.open_interest ??
      payload.extra_data?.openInterest,
  );

  return {
    eventId: eventIdValue,
    title: payload.title ?? "Untitled market",
    category: payload.category ?? undefined,
    tags: payload.tags ?? payload.extra_data?.tags ?? [],
    status: payload.status ?? undefined,
    commitDeadline:
      payload.commit_deadline ??
      payload.commitDeadline ??
      payload.closes_at ??
      payload.closesAt ??
      payload.orders_opened_at ??
      payload.ordersOpenedAt ??
      payload.extra_data?.commit_deadline ??
      payload.extra_data?.gamma?.commit_deadline ??
      payload.extra_data?.gamma?.commitDeadline ??
      payload.extra_data?.closes_at ??
      payload.extra_data?.closesAt ??
      payload.extra_data?.gamma?.closes_at ??
      payload.extra_data?.gamma?.closesAt ??
      payload.extra_data?.orders_opened_at ??
      payload.extra_data?.gamma?.orders_opened_at ??
      payload.extra_data?.gamma?.ordersOpenedAt ??
      undefined,
    revealDeadline:
      payload.reveal_deadline ??
      payload.revealDeadline ??
      payload.extra_data?.reveal_deadline ??
      payload.extra_data?.gamma?.reveal_deadline ??
      payload.extra_data?.gamma?.revealDeadline ??
      undefined,
    liquidityUsd:
      coerceNumber(payload.liquidity_usd) ??
      coerceNumber(payload.liquidityUsd) ??
      coerceNumber(payload.extra_data?.liquidity_usd) ??
      coerceNumber(payload.extra_data?.gamma?.liquidity_usd),
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
    conditionId:
      payload.condition_id ??
      payload.conditionId ??
      payload.extra_data?.condition_id ??
      payload.extra_data?.gamma?.condition_id ??
      payload.extra_data?.gamma?.conditionId ??
      undefined,
    questionId:
      payload.question_id ??
      payload.questionId ??
      payload.extra_data?.question_id ??
      payload.extra_data?.gamma?.question_id ??
      payload.extra_data?.gamma?.questionId ??
      undefined,
    umaStatus: payload.uma_resolution_status ?? undefined,
    marketAddress:
      payload.market_address ??
      payload.marketAddress ??
      payload.extra_data?.market_address ??
      payload.extra_data?.gamma?.market_address ??
      payload.extra_data?.gamma?.marketAddress ??
      undefined,
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
    featured:
      typeof payload.featured === "boolean"
        ? payload.featured
        : typeof payload.extra_data?.featured === "boolean"
          ? payload.extra_data.featured
          : typeof payload.extra_data?.gamma?.featured === "boolean"
            ? payload.extra_data.gamma.featured
            : undefined,
    clobTokenIds:
      normalizeClobTokenIds(payload.clob_token_ids) ??
      normalizeClobTokenIds(payload.clobTokenIds) ??
      normalizeClobTokenIds(payload.extra_data?.gamma?.clob_token_ids) ??
      normalizeClobTokenIds(payload.extra_data?.gamma?.clobTokenIds) ??
      undefined,
    imageVariants: payload.image_variants ?? undefined,
    groupSlug,
    groupItemTitle,
    groupItemThreshold,
    groupPosition,
    siblings,
    resolution: resolutionSource
      ? {
          resolved: Boolean(resolutionSource.resolved),
          payouts: resolutionSource.payouts ?? [],
          winners: resolutionSource.winners ?? [],
          checkedAt: resolutionSource.checkedAt,
          blockNumber: resolutionSource.blockNumber,
          transactionHash: resolutionSource.transactionHash,
        }
      : payload.resolution
        ? {
            resolved: Boolean(payload.resolution.resolved),
            payouts: payload.resolution.payouts ?? [],
            winners: payload.resolution.winners ?? [],
            checkedAt: payload.resolution.checked_at ?? payload.resolution.checkedAt,
            blockNumber: payload.resolution.block_number ?? payload.resolution.blockNumber,
            transactionHash: payload.resolution.transaction_hash ?? payload.resolution.transactionHash,
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
    createdAt: payload.created_at ?? payload.createdAt ?? payload.extra_data?.gamma?.created_at,
    updatedAt: payload.updated_at ?? payload.updatedAt ?? payload.extra_data?.gamma?.updated_at,
    extraData: payload.extra_data ?? null,
    volume24hUsd:
      coerceNumber(payload.volume_24h_usd) ??
      coerceNumber(payload.volume_24h) ??
      coerceNumber(payload.volume24h) ??
      coerceNumber(payload.extra_data?.volume_24h) ??
      coerceNumber(payload.extra_data?.gamma?.volume_24h),
    orderbookVolumeUsd:
      coerceNumber(payload.orderbook_volume_usd) ??
      coerceNumber(payload.orderbookVolumeUsd) ??
      coerceNumber(payload.extra_data?.orderbook_volume_usd),
    tradesQuantity:
      coerceNumber(payload.trades_quantity) ??
      coerceNumber(payload.tradesQuantity) ??
      coerceNumber(payload.extra_data?.trades_quantity),
    bestBid: bestBid ?? null,
    bestAsk: bestAsk ?? null,
    spread: spread ?? null,
    volume: volume ?? null,
    openInterest: openInterest ?? null,
  };
};


export async function fetchFeaturedMarkets(limit = 6, options?: FetchFeaturedMarketsOptions): Promise<MarketSummary[]> {
  if (maybeShortCircuitOffline("fetchFeaturedMarkets")) {
    return [];
  }
  try {
    const onlyFeatured = options?.onlyFeatured ?? false;
    const coalesceGroups = options?.coalesceGroups ?? true;
    let endpoint = "/markets";
    const params = new URLSearchParams();
    params.set("limit", String(limit));
    const statusParam = options?.status ?? "active";
    if (statusParam && statusParam !== "any" && statusParam !== "all") {
      params.set("status", statusParam);
    }
    const orderBy = options?.orderBy ?? "volume";
    params.set("order_by", orderBy);
    if (onlyFeatured) {
      params.set("only_featured", "1");
    }
    if (coalesceGroups) {
      params.set("coalesce_groups", "1");
    }
    const effectiveStatus = statusParam ?? "active";
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
    const trendingMode = options?.trending === true;
    if (options?.category) {
      const slug = slugify(options.category);
      endpoint = `/categories/${encodeURIComponent(slug)}`;
      fetchTags.push(`category:${slug}`);
    } else {
      fetchTags.push("markets:list");
    }
    if (trendingMode) {
      params.set("trending", "1");
      // Offsets do not combine with the backend trending slice; keep the hottest markets only.
      params.delete("offset");
    }
    const url = new URL(endpoint, DEFAULT_API_BASE);
    params.forEach((value, key) => url.searchParams.set(key, value));
    logger.debug("fetchFeaturedMarkets:request", {
      endpoint: url.toString(),
      limit,
      offset: options?.offset,
      category: options?.category,
      searchQuery: options?.searchQuery,
      status: effectiveStatus,
      trending: trendingMode,
      orderBy,
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
      orderBy,
      cacheTags: fetchTags,
    });
    const mapped: MarketSummary[] = items.map((item: any) => mapApiMarketToSummary(item));
    // Enrich with orderbook aggregates when token IDs are present (best-effort).
    try {
      const tokenIds = mapped.flatMap((m) => m.clobTokenIds ?? []).filter(Boolean) as string[];
      if (tokenIds.length) {
        const aggregates = await fetchOrderbookAggregates(tokenIds);
        mapped.forEach((market) => {
          const ids = market.clobTokenIds ?? [];
          const matching = ids.map((id) => aggregates[id]).filter(Boolean);
          if (matching.length) {
            const volume = matching.reduce(
              (acc, curr) => acc + (curr.scaledCollateralVolume ?? curr.collateralVolume ?? 0),
              0,
            );
            const trades = matching.reduce((acc, curr) => acc + (curr.tradesQuantity ?? 0), 0);
            market.orderbookVolumeUsd = volume;
            market.tradesQuantity = trades;
          }
        });
      }
    } catch (err) {
      logger.warn("fetchFeaturedMarkets:orderbook_enrich_failed", {
        error: (err as Error).message,
        count: items.length,
      });
    }
    const getUpdatedAt = (m: MarketSummary): string =>
      (m as any).updatedAt ?? (m as any).updated_at ?? m.extraData?.gamma?.updated_at ?? "";
    const scored = mapped.map((m) => ({ market: m, popularity: computePopularity(m) }));
    const sorter = (a: { market: MarketSummary; popularity: number }, b: { market: MarketSummary; popularity: number }) => {
      const diff = (b.popularity ?? 0) - (a.popularity ?? 0);
      if (diff !== 0) return diff;
      const aUpdated = getUpdatedAt(a.market);
      const bUpdated = getUpdatedAt(b.market);
      return bUpdated > aUpdated ? 1 : bUpdated < aUpdated ? -1 : 0;
    };
    const orderedByVolume = scored.sort(sorter).map((entry) => entry.market);
    return trendingMode ? orderedByVolume.slice(0, limit) : orderedByVolume;
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

type ProofReceiptFilters = {
  offset?: number;
  marketId?: number;
  eventId?: string;
  conditionId?: string;
  requestId?: string;
};

export async function fetchProofReceipts(
  limit = 20,
  options?: ProofReceiptFilters,
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
  if (options?.marketId) {
    url.searchParams.set("market_id", `${options.marketId}`);
  }
  if (options?.eventId) {
    url.searchParams.set("event_id", options.eventId);
  }
  if (options?.conditionId) {
    url.searchParams.set("condition_id", options.conditionId);
  }
  if (options?.requestId) {
    url.searchParams.set("request_id", options.requestId);
  }

  try {
    const endpoint = url.toString();
    logger.info("fetchProofReceipts:request", {
      endpoint,
      limit,
      offset,
      baseUrl: DEFAULT_API_BASE,
      filters: {
        marketId: options?.marketId,
        eventId: options?.eventId,
        conditionId: options?.conditionId,
        requestId: options?.requestId,
      },
    });
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

export async function fetchInvestorKpis(
  preloadedStats?: MarketStatusStat[],
  preloadedHealth?: HealthSnapshot | null,
): Promise<InvestorKpis> {
  const statsPromise =
    Array.isArray(preloadedStats) && preloadedStats.length >= 0
      ? Promise.resolve(preloadedStats)
      : fetchMarketStatsBreakdown();
  const healthPromise =
    typeof preloadedHealth !== "undefined" ? Promise.resolve(preloadedHealth) : fetchHealthSnapshot();

  const [statsResult, healthResult] = await Promise.allSettled([statsPromise, healthPromise]);

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
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    const response = await fetch(detailUrl, {
      signal: controller.signal,
      next: { revalidate: 30 },
    });
    clearTimeout(timeout);
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
    const detail: MarketDetail = mapMarketDetailPayload(payload, eventId);
    // Enrich with subgraph orderbook + OI when available (best-effort).
    try {
      if (!detail.clobTokenIds?.length && detail.conditionId) {
        const tokens = await fetchMarketTokens(detail.conditionId, { first: 40 });
        if (tokens.length) {
          detail.clobTokenIds = tokens;
        }
      }
      if (detail.clobTokenIds && detail.clobTokenIds.length > 0) {
        const aggregates = await fetchOrderbookAggregates(detail.clobTokenIds);
        const matching = detail.clobTokenIds.map((id) => aggregates[id]).filter(Boolean);
        if (matching.length) {
          const volume = matching.reduce(
            (acc, curr) => acc + (curr.scaledCollateralVolume ?? curr.collateralVolume ?? 0),
            0,
          );
          const trades = matching.reduce((acc, curr) => acc + (curr.tradesQuantity ?? 0), 0);
          detail.orderbookVolumeUsd = volume;
          detail.tradesQuantity = trades;
          const volume24h = matching.reduce((acc, curr) => acc + (curr.volume24h ?? 0), 0);
          if (!detail.volume24hUsd && volume24h > 0) {
            detail.volume24hUsd = volume24h;
          }
        }
      }
      if (detail.conditionId) {
        const oi = await fetchOpenInterest(detail.conditionId);
        if (oi !== undefined) {
          detail.openInterestUsd = oi;
        }
      }
    } catch (err) {
      logger.warn("fetchMarketByEventId:subgraph_enrich_failed", { eventId, error: (err as Error).message });
    }
    logger.info("fetchMarketByEventId:success", { eventId });
    return detail;
  } catch (error) {
    logOfflineAwareError("fetchMarketByEventId", error, { eventId });
    return null;
  }
}

export async function fetchGroupedMarkets(groupSlug: string): Promise<GroupedMarkets | null> {
  if (maybeShortCircuitOffline("fetchGroupedMarkets")) {
    return null;
  }
  const normalizedSlug = groupSlug.trim().toLowerCase();
  if (!normalizedSlug) return null;
  try {
    const url = `${DEFAULT_API_BASE}/markets/group/${encodeURIComponent(normalizedSlug)}`;
    logger.info("fetchGroupedMarkets:request", { groupSlug: normalizedSlug, endpoint: url });
    const response = await fetch(url, { next: { revalidate: 30 } });
    if (response.status === 404) {
      logger.warn("fetchGroupedMarkets:not_found", { groupSlug: normalizedSlug });
      return null;
    }
    if (!response.ok) {
      logger.error("fetchGroupedMarkets:failed", { groupSlug: normalizedSlug, status: response.status });
      return null;
    }
    const payload = await response.json();
    const marketsPayload = Array.isArray(payload.markets) ? payload.markets : [];
    const markets = marketsPayload.map((item: any) => mapMarketDetailPayload(item, item.event_id ?? item.eventId ?? ""));
    return {
      groupSlug: payload.group_slug ?? payload.groupSlug ?? normalizedSlug,
      markets,
      aggregateVolume24hUsd: coerceNumber(payload.aggregate_volume_24h_usd ?? payload.aggregateVolume24hUsd) ?? null,
      aggregateLiquidityUsd: coerceNumber(payload.aggregate_liquidity_usd ?? payload.aggregateLiquidityUsd) ?? null,
    };
  } catch (error) {
    logOfflineAwareError("fetchGroupedMarkets", error, { groupSlug });
    return null;
  }
}
