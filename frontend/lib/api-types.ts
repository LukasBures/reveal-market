export type MarketSibling = {
  eventId: string;
  title?: string;
  status?: string;
  groupItemTitle?: string | null;
  groupItemThreshold?: number | null;
  groupPosition?: number | null;
  outcomePrices?: number[] | null;
  volume?: number | null;
  volume24hUsd?: number | null;
  liquidityUsd?: number | null;
  commitDeadline?: string | null;
  startsAt?: string | null;
  closesAt?: string | null;
};

export type MarketSummary = {
  eventId: string;
  title: string;
  category?: string;
  tags?: string[];
  status?: string;
  resolutionStatus?: string | null;
  resolutionReason?: string | null;
  commitsBlockedAt?: string | null;
  commitDeadline?: string;
  revealDeadline?: string;
  liquidityUsd?: number;
  outcomes?: string[];
  outcomePrices?: number[];
  imageUrl?: string | null;
  rakeBps?: number | null;
  extraData?: Record<string, any> | null;
  closesAt?: string | null;
  startsAt?: string | null;
  ordersOpenedAt?: string | null;
  resolutionSource?: string | null;
  marketMaker?: string | null;
  orderMinSize?: number | null;
  priceTickSize?: number | null;
  enableOrderBook?: boolean | null;
  clobTokenIds?: string[] | null;
  imageVariants?: string[] | null;
  volume24hUsd?: number;
  orderbookVolumeUsd?: number;
  tradesQuantity?: number;
  openInterestUsd?: number;
  bestBid?: number | null;
  bestAsk?: number | null;
  spread?: number | null;
  volume?: number | null;
  openInterest?: number | null;
  groupSlug?: string | null;
  groupItemTitle?: string | null;
  groupItemThreshold?: number | null;
  groupPosition?: number | null;
  siblings?: MarketSibling[];
  featured?: boolean | null;
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
  commitmentsCount?: number | null;
  batchRoots?: string[] | null;
  batchCounts?: number[] | null;
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
  startsAt?: string | null;
  ordersOpenedAt?: string | null;
  resolutionSource?: string | null;
  marketMaker?: string | null;
  orderMinSize?: number | null;
  priceTickSize?: number | null;
  enableOrderBook?: boolean | null;
  clobTokenIds?: string[] | null;
  imageVariants?: string[] | null;
};

export type GroupedMarkets = {
  groupSlug: string;
  markets: MarketDetail[];
  aggregateVolume24hUsd?: number | null;
  aggregateVolumeTotalUsd?: number | null;
  aggregateLiquidityUsd?: number | null;
};

export type EventSummary = {
  eventId: string;
  title: string;
  category?: string;
  groupSlug?: string | null;
  imageUrl?: string | null;
  startsAt?: string | null;
  closesAt?: string | null;
  markets: MarketSummary[];
  aggregateVolume24hUsd?: number | null;
  aggregateVolumeTotalUsd?: number | null;
  aggregateLiquidityUsd?: number | null;
};

export type ProofReceipt = {
  requestId: string;
  marketId?: number | null;
  eventId?: string | null;
  conditionId?: string | null;
  marketAddress?: string | null;
  settlementTxHash?: string | null;
  proofHash?: string | null;
  proverVersion?: string | null;
  circuitHash?: string | null;
  generatedAt?: string | null;
  proof?: string | null;
  publicSignals?: string[];
  merkleRoot?: string | null;
  batchIndex?: number | null;
  totalEscrow?: string | null;
  totalLiability?: string | null;
  rakeBps?: number | null;
  winningOutcomeId?: number | null;
  poolTotalYes?: string | null;
  poolTotalNo?: string | null;
  winningPool?: string | null;
  totalPool?: string | null;
};

export type PositionRecord = {
  market_id: string;
  market_title?: string | null;
  outcome_id: number;
  outcome_label?: string | null;
  stake_wei: number;
  stake_zen: number;
  payout_wei?: number | string | null;
  payout_zen?: number | null;
  tx_hash?: string | null;
  quote_id?: string | null;
  status: string;
  ticket_id?: number | null;
  created_at?: string | null;
  claimed_at?: string | null;
  claimable?: boolean | null;
  closes_at?: string | null;
  resolved_at?: string | null;
  proof_request_id?: string | null;
  merkle_root?: string | null;
  winning_outcome_id?: number | null;
  market_address?: string | null;
  resolution_status?: string | null;
  resolution_reason?: string | null;
  commits_blocked_at?: string | null;
  potential_payout_zen?: number | null;
  potential_payout_wei?: number | string | null;
  market_summary?: {
    title?: string | null;
    outcomes?: string[] | null;
    outcome_prices?: number[] | null;
  } | null;
};

export type ClaimBundle = {
  marketId: string;
  marketAddress: string;
  commitmentsRoot: string;
  ticketId: number | string;
  outcomeId: number | string;
  amountWei: number | string;
  payoutWei: number | string;
  quoteId?: string | null;
  salt?: string | null;
  merkleProof: string[];
  leaf: string;
  user: string;
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
  status?: string;
  trending?: boolean;
  onlyFeatured?: boolean;
  orderBy?: "volume" | "recent" | "popularity";
  closesWithinHours?: number | null;
};
