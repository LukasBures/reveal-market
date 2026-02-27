import type {
  EventSummary,
  FetchFeaturedMarketsOptions,
  MarketDetail,
  MarketSibling,
  MarketStatusStat,
  MarketSummary,
  ProofReceipt,
  ClaimBundle,
  PositionRecord,
} from "./api-types";
import { slugify } from "./slugs";
import { logger } from "./logging";
import { mapApiMarketToSummary } from "./marketMapper";
import { getServerEnv } from "./serverEnv";
import { fetchMarketTokens, fetchOpenInterest, fetchOrderbookAggregates } from "./streamer-data";

/** Discriminated union for single-item API results. */
export type ApiResult<T> = { data: T; error?: undefined } | { data: null; error: string };

/** Wrapper for list-returning API functions. An empty `data` with `error` set means the request failed. */
export type ApiListResult<T> = { data: T[]; error?: string };

const resolvedEnv = getServerEnv();
export const DEFAULT_API_BASE = resolvedEnv.apiBaseUrl;
const IS_BUILD_TIME = process.env.NEXT_PHASE === "phase-production-build";
const IS_BROWSER = typeof window !== "undefined";

const DEFAULT_REVALIDATE_SECONDS = 30;
const DEFAULT_SUGGEST_REVALIDATE_SECONDS = 15;
const DEFAULT_CLOSES_WITHIN_HOURS = 24;
const DEFAULT_FETCH_TIMEOUT_MS = 8000;
const SUGGEST_FETCH_TIMEOUT_MS = 5000;
const PROOF_FETCH_TIMEOUT_MS = 12000;
const logOfflineAwareError = (scope: string, error: unknown, meta?: Record<string, unknown>) => {
  const message = error instanceof Error ? error.message : String(error ?? "unknown");
  const payload = meta ? { ...meta, error: message } : { error: message };
  const normalized = message.toLowerCase();
  const isFetchFailure = normalized.includes("fetch failed") || normalized.includes("failed to fetch");
  const event = isFetchFailure ? "unreachable" : "error";
  const loggerExt = logger as Record<string, unknown>;
  const clientWarn = typeof loggerExt.clientWarn === "function" ? (loggerExt.clientWarn as typeof logger.warn) : null;
  if (IS_BROWSER && clientWarn) {
    clientWarn(`${scope}:${event}`, payload);
    return;
  }
  const methodName = event === "error" ? "error" : "warn";
  const serverLogger =
    typeof loggerExt[methodName] === "function" ? (loggerExt[methodName] as typeof logger.warn) : logger.warn;
  serverLogger(`${scope}:${event}`, payload);
};

const maybeShortCircuitOffline = (_scope: string) => false;

type NextFetchOptions = RequestInit & { next?: { revalidate?: number; tags?: string[] } };

const fetchWithTimeout = async (url: string, options: NextFetchOptions, timeoutMs = DEFAULT_FETCH_TIMEOUT_MS) => {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timeout);
  }
};

const coerceNumber = (value: unknown): number | undefined => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
};

const coerceId = (value: unknown, fallback?: string): string => {
  const raw = value ?? fallback ?? "";
  return typeof raw === "string" ? raw.trim() : String(raw);
};

const normalizeClobTokenIds = (value: unknown): string[] | undefined => {
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

const normalizeStringArray = (value: unknown): string[] | undefined => {
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

const normalizeNumberArray = (value: unknown): number[] | undefined => {
  if (Array.isArray(value)) {
    const parsed = value.map((v) => Number(v)).filter((v) => Number.isFinite(v));
    return parsed.length ? parsed : undefined;
  }
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) {
        const nums = parsed.map((v) => Number(v)).filter((v) => Number.isFinite(v));
        return nums.length ? nums : undefined;
      }
    } catch {
      const parts = value.split(",").map((v) => v.trim()).filter(Boolean);
      const nums = parts.map((v) => Number(v)).filter((v) => Number.isFinite(v));
      if (nums.length) return nums;
    }
  }
  return undefined;
};

const humanizeGroupSlug = (slug?: string | null): string | undefined => {
  if (!slug) return undefined;
  return slug
    .split("-")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
};

const mapMarketDetailPayload = (payload: any, eventId: string): MarketDetail => {
  const eventIdValue = coerceId(payload.event_id ?? payload.eventId, eventId);
  const resolutionSource = payload.resolution ?? payload.extra_data?.resolution;
  const eventKey = payload.event_key ?? payload.eventKey ?? payload.extra_data?.event_key ?? null;
  const groupSlug = payload.group_slug ?? payload.groupSlug ?? payload.extra_data?.group_slug ?? eventKey ?? null;
  const groupTitle = payload.group_title ?? payload.groupTitle ?? payload.extra_data?.group_title ?? null;
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
  const resolutionStatus =
    payload.resolution_status ??
    payload.resolutionStatus ??
    payload.extra_data?.resolution_status ??
    payload.extra_data?.resolutionStatus ??
    null;
  const resolutionReason =
    payload.resolution_reason ??
    payload.resolutionReason ??
    payload.extra_data?.resolution_reason ??
    payload.extra_data?.resolutionReason ??
    null;
  const commitsBlockedAt =
    payload.commits_blocked_at ??
    payload.commitsBlockedAt ??
    payload.extra_data?.commits_blocked_at ??
    payload.extra_data?.commitsBlockedAt ??
    null;

  return {
    eventId: coerceId(payload.event_id ?? payload.eventId ?? eventIdValue),
    title: payload.title ?? "Untitled market",
    category: payload.category ?? undefined,
    tags: payload.tags ?? payload.extra_data?.tags ?? [],
    status: payload.status ?? undefined,
    resolutionStatus: resolutionStatus ?? undefined,
    resolutionReason: resolutionReason ?? undefined,
    commitsBlockedAt: commitsBlockedAt ?? undefined,
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
    commitmentsCount: coerceNumber(payload.commitments_count ?? payload.commitmentsCount) ?? null,
    batchRoots: normalizeStringArray(payload.batch_roots ?? payload.batchRoots) ?? null,
    batchCounts: normalizeNumberArray(payload.batch_counts ?? payload.batchCounts) ?? null,
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
    groupTitle,
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


export async function fetchFeaturedEvents(limit = 6, options?: FetchFeaturedMarketsOptions): Promise<ApiListResult<EventSummary>> {
  if (maybeShortCircuitOffline("fetchFeaturedEvents")) {
    return { data: [], error: "offline" };
  }
  if (IS_BUILD_TIME) {
    logger.info("fetchFeaturedEvents:skipped_build", {
      limit,
      category: options?.category,
      searchQuery: options?.searchQuery,
    });
    return { data: [] };
  }
  try {
    const onlyFeatured = options?.onlyFeatured ?? false;
    let endpoint = "/events";
    const params = new URLSearchParams();
    params.set("limit", String(limit));
    const statusParam = options?.status ?? "active";
    if (statusParam && statusParam !== "any" && statusParam !== "all") {
      params.set("status", statusParam);
    }
    const orderBy = options?.orderBy ?? "volume";
    params.set("order_by", orderBy);
    const closesWithinHours = options?.closesWithinHours;
    if (closesWithinHours !== null) {
      const effectiveWindow = closesWithinHours ?? DEFAULT_CLOSES_WITHIN_HOURS;
      if (Number.isFinite(effectiveWindow) && effectiveWindow > 0) {
        params.set("closes_within_hours", String(effectiveWindow));
      }
    }
    if (onlyFeatured) {
      params.set("only_featured", "1");
    }
    params.set("coalesce_groups", "1");
    const effectiveStatus = statusParam ?? "active";
    if (typeof options?.offset === "number") {
      params.set("offset", String(options.offset));
    }
    if (options?.searchQuery && !options.category) {
      const trimmedSearch = options.searchQuery.trim();
      if (trimmedSearch.length >= 2) {
        params.set("search", trimmedSearch);
      } else if (trimmedSearch.length > 0) {
        return { data: [] };
      }
    }
    const fetchTags: string[] = [];
    const trendingMode = options?.trending === true;
    if (options?.category) {
      const slug = slugify(options.category);
      params.set("category", slug);
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
    logger.debug("fetchFeaturedEvents:request", {
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
    const response = await fetchWithTimeout(
      url.toString(),
      {
        cache: "force-cache",
        next: { revalidate: options?.revalidate ?? DEFAULT_REVALIDATE_SECONDS, tags: fetchTags },
      },
      DEFAULT_FETCH_TIMEOUT_MS,
    );

    if (!response.ok) {
      logger.warn("fetchFeaturedEvents:failed", {
        status: response.status,
        endpoint: url.toString(),
        baseUrl: DEFAULT_API_BASE,
      });
      return { data: [], error: `fetch failed (${response.status})` };
    }

    const payload = await response.json();
    const items = Array.isArray(payload) ? payload : payload?.items ?? [];
    logger.debug("fetchFeaturedEvents:success", {
      limit,
      category: options?.category,
      searchQuery: options?.searchQuery,
      count: items.length,
      orderBy,
      cacheTags: fetchTags,
    });
    return { data: items.map((item: any) => {
      const marketsPayload = Array.isArray(item.markets) ? item.markets : [];
      const markets = marketsPayload.map((market: any) => mapApiMarketToSummary(market));
      const eventKey = item.event_key ?? item.eventKey ?? null;
      const groupSlug = item.group_slug ?? item.groupSlug ?? eventKey ?? null;
      const primaryMarketEventId =
        markets.find((market: MarketSummary) => Boolean(market.eventId && market.eventId !== "unknown"))?.eventId ?? null;
      const routeEventId = coerceId(primaryMarketEventId ?? item.event_id ?? item.eventId ?? "", "");
      const imageUrl = item.image_url ?? item.imageUrl ?? markets[0]?.imageUrl ?? null;
      const shouldHumanizeTitle = groupSlug && marketsPayload.length > 1;
      const title =
        item.title ??
        markets[0]?.title ??
        (shouldHumanizeTitle ? humanizeGroupSlug(groupSlug) : null) ??
        "";
      return {
        eventId: routeEventId || "unknown",
        title,
        category: item.category ?? markets[0]?.category ?? undefined,
        groupSlug: groupSlug ?? markets[0]?.groupSlug ?? null,
        imageUrl,
        startsAt: item.starts_at ?? item.startsAt ?? markets[0]?.startsAt ?? null,
        closesAt: item.closes_at ?? item.closesAt ?? markets[0]?.closesAt ?? null,
        markets,
        aggregateVolume24hUsd: coerceNumber(item.aggregate_volume_24h_usd ?? item.aggregateVolume24hUsd) ?? null,
        aggregateVolumeTotalUsd:
          coerceNumber(item.aggregate_volume_total_usd ?? item.aggregateVolumeTotalUsd) ??
          markets.reduce((max: number, market: MarketSummary) => {
            const candidate =
              coerceNumber(market.volume ?? market.orderbookVolumeUsd ?? market.volume24hUsd) ?? 0;
            return Math.max(max, candidate);
          }, 0),
        aggregateLiquidityUsd: coerceNumber(item.aggregate_liquidity_usd ?? item.aggregateLiquidityUsd) ?? null,
      } as EventSummary;
    }) };
  } catch (error) {
    logOfflineAwareError("fetchFeaturedEvents", error);
    return { data: [], error: error instanceof Error ? error.message : "unknown" };
  }
}

export async function fetchMarketSuggestions(
  query: string,
  limit = 5,
  options?: { revalidate?: number },
): Promise<ApiListResult<MarketSummary>> {
  if (maybeShortCircuitOffline("fetchMarketSuggestions")) {
    return { data: [], error: "offline" };
  }
  const trimmed = query.trim();
  if (trimmed.length < 2) {
    return { data: [] };
  }
  const normalized = trimmed.toLowerCase();
  const url = new URL("/events/suggest", DEFAULT_API_BASE);
  url.searchParams.set("limit", String(limit));
  url.searchParams.set("q", trimmed);

  try {
    logger.debug("fetchMarketSuggestions:request", {
      endpoint: url.toString(),
      limit,
      query: trimmed,
    });
    const response = await fetchWithTimeout(
      url.toString(),
      {
        cache: "force-cache",
        next: {
          revalidate: options?.revalidate ?? DEFAULT_SUGGEST_REVALIDATE_SECONDS,
          tags: [`suggest:${normalized}`],
        },
      },
      SUGGEST_FETCH_TIMEOUT_MS,
    );
    if (!response.ok) {
      logger.error("fetchMarketSuggestions:failed", { status: response.status, endpoint: url.toString() });
      return { data: [], error: `fetch failed (${response.status})` };
    }
    const payload = await response.json();
    if (!Array.isArray(payload)) {
      return { data: [] };
    }
    const mapped = payload.map(mapApiMarketToSummary);
    logger.debug("fetchMarketSuggestions:success", { query: trimmed, count: mapped.length });
    return { data: mapped };
  } catch (error) {
    logOfflineAwareError("fetchMarketSuggestions", error);
    return { data: [], error: error instanceof Error ? error.message : "unknown" };
  }
}

const normalizeMarketStats = (payload: any): MarketStatusStat[] | null => {
  if (!Array.isArray(payload)) {
    return null;
  }
  const normalized = payload.reduce<Record<string, number>>((acc, item) => {
    const key = String(item?.status ?? "unknown").toLowerCase();
    const count = Number(item?.count ?? 0);
    acc[key] = (acc[key] ?? 0) + (Number.isFinite(count) ? count : 0);
    return acc;
  }, {});
  const live = normalized["live"] ?? 0;
  const finalized = normalized["finalized"] ?? 0;
  const ended = normalized["ended"] ?? finalized;
  const total = normalized["total"] ?? live + ended;
  return [
    { status: "live", count: live },
    { status: "ended", count: ended },
    { status: "finalized", count: finalized },
    { status: "total", count: total },
  ];
};

async function fetchMarketStatsFrom(
  baseUrl: string,
  scope: string,
  revalidateSeconds = 60,
): Promise<MarketStatusStat[] | null> {
  try {
    const endpoint = `${baseUrl}/events/stats`;
    const response = await fetchWithTimeout(
      endpoint,
      {
        next: { revalidate: revalidateSeconds },
      },
      DEFAULT_FETCH_TIMEOUT_MS,
    );

    if (!response.ok) {
      logger.warn(`${scope}:failed`, { status: response.status, endpoint, baseUrl });
      return null;
    }

    const stats = normalizeMarketStats(await response.json());
    if (!stats) {
      logger.warn(`${scope}:invalid_payload`, { endpoint, baseUrl });
      return null;
    }

    logger.debug(`${scope}:success`, { count: stats.length, baseUrl });
    return stats;
  } catch (error) {
    logOfflineAwareError(scope, error, { baseUrl });
    return null;
  }
}

export async function fetchMarketStatsBreakdown(): Promise<ApiListResult<MarketStatusStat>> {
  if (maybeShortCircuitOffline("fetchMarketStatsBreakdown")) {
    return { data: [], error: "offline" };
  }
  const primaryStats = await fetchMarketStatsFrom(DEFAULT_API_BASE, "fetchMarketStatsBreakdown");
  return { data: primaryStats ?? [] };
}

type ProofReceiptFilters = {
  offset?: number;
  marketId?: number;
  eventId?: string;
  conditionId?: string;
  requestId?: string;
};

export async function fetchTradeStatus(
  txHash?: string | null,
  jobId?: string | null,
): Promise<{ status: string; txHash?: string; blockNumber?: number | null }> {
  if (!txHash && !jobId) {
    return { status: "unknown" };
  }
  const url = new URL(`${DEFAULT_API_BASE}/trade/status`);
  if (txHash) url.searchParams.set("tx_hash", txHash);
  if (jobId) url.searchParams.set("job_id", jobId);
  try {
    const response = await fetchWithTimeout(
      url.toString(),
      { cache: "no-store" },
      DEFAULT_FETCH_TIMEOUT_MS,
    );
    if (!response.ok) {
      return { status: "unknown" };
    }
    const payload = await response.json();
    return {
      status: payload?.status ?? "unknown",
      txHash: payload?.tx_hash ?? txHash ?? undefined,
      blockNumber: payload?.block_number ?? null,
    };
  } catch {
    return { status: "unknown" };
  }
}

export async function fetchPositions(
  wallet: string,
): Promise<{ positions: PositionRecord[]; escrowBalance?: string | number | null; error?: string }> {
  if (maybeShortCircuitOffline("fetchPositions")) {
    return { positions: [], error: "offline" };
  }
  const url = new URL(`${DEFAULT_API_BASE}/positions`);
  url.searchParams.set("wallet", wallet);
  try {
    const response = await fetchWithTimeout(
      url.toString(),
      { cache: "no-store" },
      DEFAULT_FETCH_TIMEOUT_MS,
    );
    if (!response.ok) {
      const detail = await response.text();
      const errorMessage = `Failed to fetch positions (${response.status}): ${detail}`;
      logger.error("fetchPositions:failed", { status: response.status, endpoint: url.toString() });
      return { positions: [], error: errorMessage };
    }
    const payload = await response.json();
    if (Array.isArray(payload)) {
      return { positions: payload as PositionRecord[] };
    }
    const escrow = payload?.escrow_balance_wei ?? payload?.escrowBalance ?? null;
    return {
      positions: Array.isArray(payload?.positions) ? (payload.positions as PositionRecord[]) : [],
      escrowBalance: escrow,
    };
  } catch (error) {
    logOfflineAwareError("fetchPositions", error);
    return { positions: [], error: (error as Error).message };
  }
}

export async function fetchClaimBundles(
  wallet: string,
  signature: string,
): Promise<{
  bundles: ClaimBundle[];
  status?: string;
  pendingMarkets?: string[];
  error?: string;
}> {
  if (maybeShortCircuitOffline("fetchClaimBundles")) {
    return { bundles: [], error: "offline" };
  }
  const url = new URL(`${DEFAULT_API_BASE}/claim/bundles`);
  url.searchParams.set("wallet", wallet);
  try {
    const response = await fetchWithTimeout(
      url.toString(),
      {
        cache: "no-store",
        headers: { "X-Wallet-Signature": signature },
      },
      PROOF_FETCH_TIMEOUT_MS,
    );
    if (!response.ok) {
      const detail = await response.text();
      const errorMessage = `Failed to fetch claim bundles (${response.status}): ${detail}`;
      logger.error("fetchClaimBundles:failed", { status: response.status, endpoint: url.toString() });
      return { bundles: [], error: errorMessage };
    }
    const payload = await response.json();
    const bundles = Array.isArray(payload?.bundles) ? (payload.bundles as ClaimBundle[]) : [];
    return {
      bundles,
      status: payload?.status,
      pendingMarkets: Array.isArray(payload?.pendingMarkets)
        ? (payload.pendingMarkets as string[])
        : undefined,
      error: payload?.error,
    };
  } catch (error) {
    logOfflineAwareError("fetchClaimBundles", error);
    return { bundles: [], error: (error as Error).message };
  }
}

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
    const response = await fetchWithTimeout(
      endpoint,
      {
        next: { revalidate: DEFAULT_REVALIDATE_SECONDS },
      },
      PROOF_FETCH_TIMEOUT_MS,
    );
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

export async function fetchMarketByEventId(eventId: string, eventKey?: string | null): Promise<ApiResult<MarketDetail>> {
  if (maybeShortCircuitOffline("fetchMarketByEventId")) {
    return { data: null, error: "offline" };
  }
  try {
    const lookupKey = (eventKey ?? eventId).trim();
    const detailUrl = `${DEFAULT_API_BASE}/events/by-key/${lookupKey}`;
    logger.info("fetchMarketByEventId:request", { eventId, eventKey: lookupKey, endpoint: detailUrl });
    const response = await fetchWithTimeout(
      detailUrl,
      {
        next: { revalidate: 30 },
      },
      DEFAULT_FETCH_TIMEOUT_MS,
    );
    if (response.status === 404) {
      logger.warn("fetchMarketByEventId:not_found", { eventId });
      return { data: null, error: "not_found" };
    }
    if (!response.ok) {
      logger.error("fetchMarketByEventId:failed", {
        eventId,
        status: response.status,
        endpoint: detailUrl,
        baseUrl: DEFAULT_API_BASE,
      });
      return { data: null, error: `fetch failed (${response.status})` };
    }
    const payload = await response.json();
    const groupTitle =
      payload.group_title ?? payload.groupTitle ?? payload.extra_data?.group_title ?? payload.extraData?.groupTitle ?? null;
    const marketsPayload = Array.isArray(payload.markets) ? payload.markets : [];
    const groupMarkets = marketsPayload.length
      ? marketsPayload.map((item: any) =>
          mapMarketDetailPayload(item, item.event_id ?? item.eventId ?? ""),
        )
      : [mapMarketDetailPayload(payload, eventId)];
    const selected =
      groupMarkets.find((item: MarketDetail) => String(item.eventId) === String(eventId)) ?? groupMarkets[0] ?? null;
    const detail: MarketDetail = selected ?? mapMarketDetailPayload(payload, eventId);
    detail.groupSlug = payload.group_slug ?? payload.groupSlug ?? payload.event_key ?? payload.eventKey ?? detail.groupSlug;
    detail.groupTitle = groupTitle ?? detail.groupTitle ?? null;
    detail.groupMarkets = groupMarkets;
    // Group-level resolution/heartbeat may exist only on the parent event payload.
    if (!detail.resolution && payload.extra_data?.resolution) {
      detail.resolution = payload.extra_data.resolution;
    }
    if (!detail.heartbeat && payload.extra_data?.heartbeat) {
      const hb = payload.extra_data.heartbeat;
      detail.heartbeat = {
        timestamp: hb.timestamp ?? hb.checkedAt ?? null,
        latencyMs: coerceNumber(hb.latency_ms ?? hb.latencyMs),
      };
    }
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
    return { data: detail };
  } catch (error) {
    logOfflineAwareError("fetchMarketByEventId", error, { eventId });
    return { data: null, error: error instanceof Error ? error.message : "unknown" };
  }
}
