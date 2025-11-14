export type MarketSummary = {
  eventId: string;
  title: string;
  category?: string;
  tags?: string[];
  status?: string;
  commitDeadline?: string;
  revealDeadline?: string;
  liquidityUsd?: number;
  outcomes?: string[];
  outcomePrices?: number[];
  imageUrl?: string | null;
  rakeBps?: number | null;
};

export type MarketDetail = MarketSummary & {
  description?: string;
  oracle?: string;
  createdAt?: string;
  updatedAt?: string;
  slug?: string;
  factory?: string;
  conditionId?: string;
  questionId?: string;
  umaStatus?: string;
  marketAddress?: string;
  resolution?: {
    resolved: boolean;
    payouts?: number[];
    winners?: { index: number; label?: string; payout: number }[];
    checkedAt?: string;
    blockNumber?: number;
    transactionHash?: string;
    proofUrl?: string;
  };
  extraData?: Record<string, any> | null;
  heartbeat?: {
    timestamp?: string;
    latencyMs?: number;
  } | null;
};

export type ProofReceipt = {
  proofNonce: string;
  verifier: string;
  marketAddress: string;
  transactionHash: string;
  blockNumber?: number;
  verifiedAt: string;
  status: "verified" | "failed";
  zkVerifyReceipt?: string | null;
  circuitVersion: number;
  outcomeHash: string;
  winningPool: string;
  totalPool: string;
};

export type MarketStatusStat = {
  status: string;
  count: number;
};

export type HealthSnapshot = {
  status: string;
  timestamp?: string;
  databaseLatencyMs?: number | null;
  redisLatencyMs?: number | null;
  workerHeartbeat?: {
    marketsProcessed?: number;
    latencyMs?: number;
    timestamp?: string;
  } | null;
};

export type InvestorKpis = {
  openMarkets: number;
  settledMarkets: number;
  databaseLatencyMs: number | null;
  lastUpdatedIso: string | null;
};

export type FetchFeaturedMarketsOptions = {
  searchQuery?: string;
  category?: string;
  offset?: number;
  revalidate?: number;
};
