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
const USE_MOCK_API = process.env.NEXT_PUBLIC_API_MOCK === "true" || process.env.RM_API_MOCK === "true";

const DEFAULT_REVALIDATE_SECONDS = 30;

const MOCK_TIMESTAMP = "2025-01-10T12:00:00.000Z";

const MOCK_MARKETS: MarketDetail[] = [
  {
    eventId: "evt-us-election",
    title: "Will the incumbent win the U.S. presidential election?",
    category: "Politics",
    tags: ["Gov shutdown", "Elections"],
    status: "commit",
    commitDeadline: "2025-10-15T00:00:00.000Z",
    revealDeadline: "2025-11-08T00:00:00.000Z",
    liquidityUsd: 125000,
    outcomes: ["Incumbent wins", "Challenger wins"],
    outcomePrices: [0.57, 0.43],
    imageUrl: null,
    description: "Mock data used for frontend smoke tests without the backend.",
    oracle: "Reveal Market Oracle",
    createdAt: "2025-01-01T00:00:00.000Z",
    updatedAt: "2025-01-05T00:00:00.000Z",
    extraData: {
      tags: ["Gov shutdown"],
    },
  },
  {
    eventId: "evt-btc-halving",
    title: "Will BTC trade above $120k before the halving + 90d window?",
    category: "Crypto",
    tags: ["BTC halving"],
    status: "locked",
    commitDeadline: "2025-03-01T00:00:00.000Z",
    revealDeadline: "2025-06-28T00:00:00.000Z",
    liquidityUsd: 87000,
    outcomes: ["Yes", "No"],
    outcomePrices: [0.48, 0.52],
    description: "Local-only mock market for crypto category smoke tests.",
    oracle: "Reveal Market Oracle",
    createdAt: "2024-12-12T00:00:00.000Z",
    updatedAt: "2025-01-03T00:00:00.000Z",
    extraData: {
      tags: ["BTC halving"],
    },
  },
  {
    eventId: "evt-ai-regulation",
    title: "Will the EU pass the AI Safety Act before year end?",
    category: "AI & Tech",
    tags: ["AI regulation", "EU elections"],
    status: "settled",
    commitDeadline: "2024-09-01T00:00:00.000Z",
    revealDeadline: "2024-12-20T00:00:00.000Z",
    liquidityUsd: 54000,
    outcomes: ["Yes", "No"],
    outcomePrices: [0.0, 1.0],
    description: "Resolved mock market covering the docs/legal routes.",
    oracle: "Reveal Market Oracle",
    createdAt: "2024-06-01T00:00:00.000Z",
    updatedAt: "2024-12-22T00:00:00.000Z",
    resolution: {
      resolved: true,
      payouts: [1, 0],
      winners: [{ index: 0, label: "Yes", payout: 1 }],
      checkedAt: "2024-12-21T00:00:00.000Z",
      blockNumber: 123456789,
      transactionHash: "0xmockhash",
    },
    extraData: {
      tags: ["AI regulation"],
    },
  },
  {
    eventId: "evt-world-cup",
    title: "Will the host nation reach the World Cup semi-finals?",
    category: "Sports",
    tags: ["World Cup"],
    status: "commit",
    commitDeadline: "2026-05-01T00:00:00.000Z",
    revealDeadline: "2026-07-15T00:00:00.000Z",
    liquidityUsd: 32000,
    outcomes: ["Yes", "No"],
    outcomePrices: [0.35, 0.65],
    description: "Sports-focused mock market for local builds.",
    oracle: "Reveal Market Oracle",
    createdAt: "2025-01-08T00:00:00.000Z",
    updatedAt: "2025-01-09T00:00:00.000Z",
    extraData: {
      tags: ["World Cup"],
    },
  },
];

const MOCK_MARKET_STATS: MarketStatusStat[] = (() => {
  const tally = new Map<string, number>();
  for (const market of MOCK_MARKETS) {
    const key = (market.status ?? "unknown").toLowerCase();
    tally.set(key, (tally.get(key) ?? 0) + 1);
  }
  return Array.from(tally.entries()).map(([status, count]) => ({ status, count }));
})();

const MOCK_HEALTH_SNAPSHOT: HealthSnapshot = {
  status: "ok",
  timestamp: MOCK_TIMESTAMP,
  databaseLatencyMs: 9,
  redisLatencyMs: 3,
  workerHeartbeat: {
    marketsProcessed: 128,
    latencyMs: 42,
    timestamp: MOCK_TIMESTAMP,
  },
};

const MOCK_PROOF_RECEIPTS: ProofReceipt[] = [
  {
    proofNonce: "0x1f2c5b6a01",
    verifier: "0x9f1e212312312312312312312312312312312312",
    marketAddress: "0xA111111111111111111111111111111111111111",
    transactionHash: "0xbeef00112233445566778899aabbccddeeff00112233445566778899aabbccdd",
    blockNumber: 19001234,
    verifiedAt: "2025-01-10T12:30:00.000Z",
    status: "verified",
    zkVerifyReceipt: "vfy_0x9cdd5566",
    circuitVersion: 1,
    outcomeHash: "0x8c86462d2dc9bf1f2a2c2ff264bfaed596d632bcf66da68be2f989dff1a32310",
    winningPool: "200000000",
    totalPool: "400000000"
  },
  {
    proofNonce: "0x1f2c5b6a02",
    verifier: "0x9f1e212312312312312312312312312312312312",
    marketAddress: "0xB222222222222222222222222222222222222222",
    transactionHash: "0xca8000112233445566778899aabbccddeeff00112233445566778899aabbcd01",
    blockNumber: 19005555,
    verifiedAt: "2025-01-11T04:12:00.000Z",
    status: "verified",
    zkVerifyReceipt: null,
    circuitVersion: 1,
    outcomeHash: "0x0d4c5da73f8b849ca7322a5a70d94e17b0e2a63b0e2532f797da9c7bd8761f5f",
    winningPool: "150000000",
    totalPool: "300000000"
  },
  {
    proofNonce: "0x1f2c5b6a03",
    verifier: "0x9f1e212312312312312312312312312312312312",
    marketAddress: "0xC333333333333333333333333333333333333333",
    transactionHash: "0x8a7000112233445566778899aabbccddeeff00112233445566778899aabbceef",
    blockNumber: 19008888,
    verifiedAt: "2025-01-12T09:45:00.000Z",
    status: "verified",
    zkVerifyReceipt: "vfy_0x8aa91234",
    circuitVersion: 1,
    outcomeHash: "0x6eac0d1311439412fc0f9b8679513762c508d57f075444ef98a32956543feadd",
    winningPool: "50000000",
    totalPool: "100000000"
  }
];

function clone<T>(value: T): T {
  if (typeof globalThis.structuredClone === "function") {
    return globalThis.structuredClone(value);
  }
  return JSON.parse(JSON.stringify(value)) as T;
}

function mockMarketToSummary(market: MarketDetail): MarketSummary {
  const { eventId, title, category, tags, status, commitDeadline, revealDeadline, liquidityUsd, outcomes, outcomePrices, imageUrl } =
    market;
  return {
    eventId,
    title,
    category,
    tags: tags ? [...tags] : undefined,
    status,
    commitDeadline,
    revealDeadline,
    liquidityUsd,
    outcomes: outcomes ? [...outcomes] : undefined,
    outcomePrices: outcomePrices ? [...outcomePrices] : undefined,
    imageUrl,
  };
}

function resolveMockMarkets(limit = 6, options?: FetchFeaturedMarketsOptions): MarketSummary[] {
  const offset = options?.offset ?? 0;
  let dataset = [...MOCK_MARKETS];

  if (options?.category) {
    const categorySlug = slugify(options.category);
    dataset = dataset.filter((market) => (market.category ? slugify(market.category) : "") === categorySlug);
  } else if (options?.searchQuery) {
    const query = options.searchQuery.toLowerCase().trim();
    dataset = dataset.filter((market) => market.title.toLowerCase().includes(query));
  }

  return dataset.slice(offset, offset + limit).map(mockMarketToSummary);
}

function findMockMarketDetail(eventId: string): MarketDetail | null {
  const market = MOCK_MARKETS.find((item) => item.eventId === eventId);
  return market ? clone(market) : null;
}

export function getMockMarkets(): MarketDetail[] {
  return MOCK_MARKETS.map((market) => clone(market));
}

export async function fetchFeaturedMarkets(limit = 6, options?: FetchFeaturedMarketsOptions): Promise<MarketSummary[]> {
  if (USE_MOCK_API) {
    logger.info("fetchFeaturedMarkets:mock", { limit, options });
    return resolveMockMarkets(limit, options);
  }
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

export async function fetchMarketStatsBreakdown(): Promise<MarketStatusStat[]> {
  if (USE_MOCK_API) {
    logger.info("fetchMarketStatsBreakdown:mock");
    return MOCK_MARKET_STATS.map((stat) => ({ ...stat }));
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
  if (USE_MOCK_API) {
    logger.info("fetchHealthSnapshot:mock");
    return clone(MOCK_HEALTH_SNAPSHOT);
  }
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
      databaseLatencyMs: components?.database?.latency_ms ?? null,
      redisLatencyMs: components?.redis?.latency_ms ?? null,
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

type FetchProofReceiptsOptions = {
  offset?: number;
};

export async function fetchProofReceipts(
  limit = 20,
  options?: FetchProofReceiptsOptions,
): Promise<ProofReceipt[]> {
  const offset = Math.max(0, options?.offset ?? 0);
  if (USE_MOCK_API) {
    logger.info("fetchProofReceipts:mock", { limit, offset });
    return clone(MOCK_PROOF_RECEIPTS.slice(offset, offset + limit));
  }

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

  const stats =
    statsResult.status === "fulfilled" ? statsResult.value : [];
  const health =
    healthResult.status === "fulfilled" ? healthResult.value : null;

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
  if (USE_MOCK_API) {
    logger.info("fetchMarketByEventId:mock", { eventId });
    return findMockMarketDetail(eventId);
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
      logger.error("fetchMarketByEventId:failed", { eventId, status: response.status, endpoint: detailUrl, baseUrl: DEFAULT_API_BASE });
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
      imageUrl: payload.image_url ?? null,
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
