import type { PricingQuote } from "@/lib/pricing-client";
import { roundDown } from "@/lib/formatters";

const formatDecimal = (value: number | string | null | undefined, decimals = 4): string => {
  if (value === null || value === undefined) return "n/a";
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric)) return "n/a";
  return roundDown(numeric, decimals).toFixed(decimals);
};

export const buildCommitSignatureMessage = (quote: PricingQuote, walletAddress: string): string => {
  const wallet = walletAddress.toLowerCase();
  const quoteId = quote.quote_id ?? "";
  const marketId = quote.market_id ?? "n/a";
  const outcomeId =
    quote.outcome_id === null || quote.outcome_id === undefined ? "n/a" : String(Math.trunc(quote.outcome_id));
  const stakeZen = formatDecimal(quote.stake_zen);
  const payoutZen = formatDecimal(quote.payout_zen);
  return [
    "RevealMarket Buy Confirmation",
    "",
    `Market ID: ${marketId}`,
    `Outcome ID: ${outcomeId}`,
    `You pay: ${stakeZen} ZEN`,
    `You can win: ${payoutZen} ZEN`,
    `Quote ID: ${quoteId}`,
    `Wallet: ${wallet}`,
    "",
    "By signing, you authorize RevealMarket to submit this buy.",
  ].join("\n");
};
