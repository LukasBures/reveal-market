import type { PricingQuote } from "@/lib/pricing-client";

const formatDecimal = (value: number | string | null | undefined, maxDecimals = 8): string => {
  if (value === null || value === undefined) return "n/a";
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric)) return "n/a";
  const fixed = numeric.toFixed(maxDecimals);
  return fixed.replace(/\.?0+$/, "") || "0";
};

const normalizeWei = (value: string | number | null | undefined): string => {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed.length ? trimmed : "0";
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return Math.trunc(value).toString();
  }
  return "0";
};

export const buildCommitSignatureMessage = (quote: PricingQuote, walletAddress: string): string => {
  const wallet = walletAddress.toLowerCase();
  const quoteId = quote.quote_id ?? "";
  const marketId = quote.market_id ?? "n/a";
  const outcomeId =
    quote.outcome_id === null || quote.outcome_id === undefined ? "n/a" : String(Math.trunc(quote.outcome_id));
  const stakeZen = formatDecimal(quote.stake_zen);
  const stakeWei = normalizeWei(quote.stake_wei);
  const payoutZen = formatDecimal(quote.payout_zen);
  return [
    "RevealMarket Buy Confirmation",
    "",
    `Market ID: ${marketId}`,
    `Outcome ID: ${outcomeId}`,
    `You pay: ${stakeZen} ZEN (${stakeWei} wei)`,
    `You can win: ${payoutZen} ZEN`,
    `Quote ID: ${quoteId}`,
    `Wallet: ${wallet}`,
    "",
    "By signing, you authorize RevealMarket to submit this buy.",
  ].join("\n");
};
