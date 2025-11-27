"use client";

import type { MarketDetail } from "@/lib/api-types";
import { formatDate, formatDateTime, formatUsd } from "@/lib/formatters";

type Props = {
  market: MarketDetail;
};

type LooseRecord = Record<string, unknown>;

const toRecord = (value: unknown): LooseRecord | null =>
  value && typeof value === "object" ? (value as LooseRecord) : null;

const coerceNumber = (value: unknown): number | null => {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value === "string") {
    const parsed = Number(value.replace(/,/g, ""));
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
};

const pickNumber = (sources: Array<LooseRecord | null>, keys: string[]): number | null => {
  for (const source of sources) {
    if (!source) continue;
    for (const key of keys) {
      if (key in source) {
        const value = source[key];
        const parsed = coerceNumber(value);
        if (parsed !== null) {
          return parsed;
        }
      }
    }
  }
  return null;
};

const pickString = (sources: Array<LooseRecord | null>, keys: string[]): string | null => {
  for (const source of sources) {
    if (!source) continue;
    for (const key of keys) {
      if (key in source) {
        const value = source[key];
        if (typeof value === "string" && value.trim()) {
          return value.trim();
        }
      }
    }
  }
  return null;
};

const pickStringArray = (sources: Array<LooseRecord | null>, keys: string[]): string[] | null => {
  for (const source of sources) {
    if (!source) continue;
    for (const key of keys) {
      if (key in source) {
        const value = source[key];
        if (Array.isArray(value) && value.length > 0) {
          return value.map((entry) => String(entry));
        }
      }
    }
  }
  return null;
};

const normalizeBps = (value: number | null): number | null => {
  if (value === null || !Number.isFinite(value)) {
    return null;
  }
  if (value < 0) {
    return null;
  }
  if (value === 0) {
    return 0;
  }
  if (value <= 1) {
    return Math.round(value * 10_000);
  }
  if (value <= 100) {
    return Math.round(value * 100);
  }
  return Math.round(value);
};

const formatProbability = (value: number | null): string => {
  if (value === null) {
    return "—";
  }
  const normalized = value > 1 ? value : value * 100;
  const decimals = normalized >= 10 ? 0 : 2;
  return `${normalized.toFixed(decimals)}%`;
};

const formatBps = (value: number | null): string => {
  if (value === null) {
    return "—";
  }
  return `${value} bps`;
};

export function MarketDetailSidebar({ market }: Props) {
  const resolution = market.resolution ?? (market.extraData?.resolution as any);
  const tags = market.tags ?? [];
  const extraData = toRecord(market.extraData);
  const gamma = toRecord(extraData?.gamma);
  const sources: Array<LooseRecord | null> = [extraData, gamma];

  const liquidity =
    market.liquidityUsd ??
    pickNumber(sources, ["liquidity_usd", "liquidityUsd", "liquidityUSD", "liquidity"]);
  const volume24h = pickNumber(sources, [
    "volume24h",
    "volume24H",
    "volume_24h",
    "volume24hr",
    "volume24Hr",
    "volume_24hr",
    "volume24",
    "volume24Usd",
    "volume24hUsd",
  ]);
  const totalVolume = pickNumber(sources, ["totalVolume", "total_volume", "volume", "volumeUsd", "volumeUSD"]);
  const openInterest = pickNumber(sources, ["openInterest", "open_interest", "openInterestUsd", "openInterestUSD"]);
  const bestBid = pickNumber(sources, ["bestBid", "best_bid", "bestBidPrice"]);
  const bestAsk = pickNumber(sources, ["bestAsk", "best_ask", "bestAskPrice"]);
  const makerFeeBps = normalizeBps(
    pickNumber(sources, ["makerFeeBps", "maker_fee_bps", "makerFeeRate", "maker_fee", "makerFee"]),
  );
  const takerFeeBps = normalizeBps(
    pickNumber(sources, ["takerFeeBps", "taker_fee_bps", "takerFeeRate", "taker_fee", "takerFee"]),
  );
  const upstreamFee = pickNumber(sources, ["feeBps", "fee_bps", "feeRate", "fee", "platformFee", "protocolFee", "rake_bps"]);
  const rakeBps = (typeof market.rakeBps === "number" && Number.isFinite(market.rakeBps)
    ? Math.round(market.rakeBps)
    : null) ?? normalizeBps(upstreamFee);

  const clobPairId = pickString(sources, ["clobPairId", "pairId", "clob_pair_id"]);
  const tokenIds =
    pickStringArray(sources, ["clobTokenIds", "tokenIds", "clob_token_ids", "tokens"]) ?? undefined;

  const tradingStats = [
    { label: "24h volume", value: volume24h, formatted: formatUsd(volume24h) },
    { label: "Total volume", value: totalVolume, formatted: formatUsd(totalVolume) },
    { label: "Open interest", value: openInterest, formatted: formatUsd(openInterest) },
    { label: "Best bid", value: bestBid, formatted: formatProbability(bestBid) },
    { label: "Best ask", value: bestAsk, formatted: formatProbability(bestAsk) },
  ];

  const feeRows = [
    { label: "Rake", value: formatBps(rakeBps) },
    { label: "Maker fee", value: formatBps(makerFeeBps) },
    { label: "Taker fee", value: formatBps(takerFeeBps) },
  ].filter((row) => row.value !== "—");

  return (
    <aside className="space-y-6 rounded-3xl border border-white/10 bg-slate-900/70 p-6">
      <div className="space-y-3 rounded-2xl border border-white/10 bg-slate-950/50 p-5 text-sm text-slate-300">
        <div className="flex items-center justify-between">
          <span>Category</span>
          <span className="font-semibold text-white">{market.category ?? "General"}</span>
        </div>
        <div className="flex items-center justify-between">
          <span>Status</span>
          <span
            className={`rounded-full px-3 py-1 text-xs font-semibold ${
              resolution?.resolved ? "bg-emerald-500/20 text-emerald-300" : "bg-brand-500/20 text-brand-200"
            }`}
          >
            {resolution?.resolved ? "Resolved" : market.status ?? "Active"}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span>Created</span>
          <span className="text-white">{formatDateTime(market.createdAt)}</span>
        </div>
        <div className="flex items-center justify-between">
          <span>Liquidity</span>
          <span className="text-white">{formatUsd(liquidity)}</span>
        </div>
      </div>
      <div className="space-y-3 rounded-2xl border border-white/10 bg-slate-950/50 p-5 text-sm text-slate-300">
        <div className="flex items-center justify-between">
          <span>Commit deadline</span>
          <span className="text-white">{formatDateTime(market.commitDeadline)}</span>
        </div>
        <div className="flex items-center justify-between">
          <span>Reveal deadline</span>
          <span className="text-white">{formatDateTime(market.revealDeadline)}</span>
        </div>
        {tags.length > 0 && (
          <div>
            <span className="text-xs uppercase tracking-[0.3em] text-slate-500">Tags</span>
            <div className="mt-2 flex flex-wrap gap-2 text-xs">
              {tags.map((tag) => (
                <span key={tag} className="rounded-full bg-brand-500/15 px-3 py-1 text-brand-200">
                  #{tag}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
      <div className="space-y-3 rounded-2xl border border-white/10 bg-slate-950/50 p-5 text-sm text-slate-300">
        <div className="flex items-center justify-between">
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Trading metrics</p>
          <span
            className={`rounded-full px-2 py-1 text-[11px] uppercase tracking-[0.2em] ${
              tradingStats.some((s) => s.value !== null && s.value !== undefined)
                ? "bg-emerald-500/15 text-emerald-100"
                : "bg-amber-500/15 text-amber-100"
            }`}
          >
            {tradingStats.some((s) => s.value !== null && s.value !== undefined) ? "Live" : "Awaiting data"}
          </span>
        </div>
        <div className="space-y-3">
          {tradingStats.map((stat) => (
            <div key={stat.label} className="flex items-center justify-between">
              <span>{stat.label}</span>
              <span className="text-white">{stat.formatted}</span>
            </div>
          ))}
        </div>
      </div>
      {feeRows.length > 0 && (
        <div className="space-y-3 rounded-2xl border border-white/10 bg-slate-950/50 p-5 text-sm text-slate-300">
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Fee schedule</p>
          <div className="space-y-3">
            {feeRows.map((row) => (
              <div key={row.label} className="flex items-center justify-between">
                <span>{row.label}</span>
                <span className="text-white">{row.value}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {(clobPairId || (tokenIds?.length ?? 0) > 0) && (
        <div className="rounded-2xl border border-white/10 bg-slate-950/40 p-5 text-sm text-slate-300">
          <p className="text-xs uppercase tracking-[0.35em] text-slate-500">Order book routing</p>
          {clobPairId && (
            <div className="mt-3">
              <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Pair ID</p>
              <p className="mt-1 break-all font-mono text-xs text-white">{clobPairId}</p>
            </div>
          )}
          {tokenIds?.length ? (
            <div className="mt-3">
              <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Token IDs</p>
              <p className="mt-1 break-words font-mono text-xs text-white">{tokenIds.join(", ")}</p>
            </div>
          ) : null}
        </div>
      )}
      {resolution && (
        <div className="rounded-2xl border border-white/10 bg-slate-950/40 p-5 text-sm text-slate-300">
          <p className="text-xs uppercase tracking-[0.35em] text-slate-500">Settlement proof</p>
          <p className="mt-2">Checked at {formatDate(resolution.checkedAt)}</p>
          {resolution.transactionHash && (
            <p className="mt-2 break-all text-xs text-slate-500">TX: {resolution.transactionHash}</p>
          )}
          {resolution.blockNumber && (
            <p className="text-xs text-slate-500">Block #{resolution.blockNumber}</p>
          )}
        </div>
      )}
    </aside>
  );
}
