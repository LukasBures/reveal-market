"use client";

import type { PricingQuote } from "@/lib/pricing-client";
import { formatTime } from "@/lib/formatters";

type QuoteDisplayProps = {
  quote: PricingQuote | null;
  toWinZen: number | null;
  stakeZen: number;
  quoteCountdown: string | null;
  shortQuoteId: string | null;
  quoteExpiryMs: number | null;
};

const formatNumber = (value: number, decimals = 4) => {
  if (!Number.isFinite(value)) return "—";
  return value.toFixed(decimals);
};

const formatPreStakeCap = (
  remaining: number | null | undefined,
  stake: number | null | undefined,
  maxCap: number | null | undefined,
): string => {
  if (remaining === null || remaining === undefined || Number.isNaN(remaining)) {
    return "n/a";
  }
  const stakeValue = typeof stake === "number" && !Number.isNaN(stake) ? stake : 0;
  const preStake = Math.max(0, remaining + stakeValue);
  if (typeof maxCap === "number" && !Number.isNaN(maxCap)) {
    return `${Math.min(preStake, maxCap).toFixed(3)} ZEN`;
  }
  return `${preStake.toFixed(3)} ZEN`;
};

function Metric({ label, value, highlight = false }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="rounded-xl border border-white/10 bg-slate-900/60 px-3 py-2">
      <p className="text-[11px] uppercase tracking-[0.25em] text-slate-500">{label}</p>
      <p className={`text-sm font-semibold ${highlight ? "text-emerald-200" : "text-white"}`}>{value}</p>
    </div>
  );
}

export function QuoteDisplay({
  quote,
  toWinZen,
  stakeZen: _stakeZen,
  quoteCountdown,
  shortQuoteId,
  quoteExpiryMs,
}: QuoteDisplayProps) {
  return (
    <>
      <div className="grid grid-cols-1 gap-3 text-xs">
        <Metric label="To win" value={`${formatNumber(toWinZen ?? NaN, 3)} ZEN`} highlight />
      </div>

      {quote && (
        <p className="text-xs text-slate-300">
          Stake {formatNumber(quote.stake_zen, 3)} ZEN → Win {formatNumber(toWinZen ?? NaN, 3)} ZEN
        </p>
      )}

      {shortQuoteId && (
        <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">
          Quote id: <span className="font-semibold text-white">{shortQuoteId}</span>
        </p>
      )}
      {quote && (
        <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">
          Quote {shortQuoteId ?? "preview"} expires in{" "}
          {quoteCountdown ?? formatTime(quote.expires_at ?? quoteExpiryMs ?? undefined)}
        </p>
      )}
      {quote && (
        <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">
          Caps — user:{" "}
          {formatPreStakeCap(
            quote.remaining_user_stake_zen,
            quote.stake_zen,
            quote.max_user_stake_per_market_zen,
          )}
          , market:{" "}
          {formatPreStakeCap(
            quote.remaining_market_stake_zen,
            quote.stake_zen,
            quote.max_market_stake_zen,
          )}
        </p>
      )}
    </>
  );
}
