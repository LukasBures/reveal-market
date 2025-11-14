import { memo } from "react";
import type { MarketSummary } from "@/lib/api-types";
import { MarketCard } from "./MarketCard";

type Props = {
  markets: MarketSummary[];
};

const MemoizedMarketCard = memo(MarketCard);

export const MarketGrid = memo(function MarketGrid({ markets }: Props) {
  if (markets.length === 0) {
    return (
      <div className="rounded-3xl border border-white/5 bg-slate-900/40 p-10 text-center text-slate-400">
        Markets will appear here once data is available.
      </div>
    );
  }

  return (
    <div className="fade-up grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
      {markets.map((market) => (
        <MemoizedMarketCard key={market.eventId} market={market} />
      ))}
    </div>
  );
});
