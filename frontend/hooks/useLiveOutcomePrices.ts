import { useEffect, useMemo } from "react";
import { seedInitialOutcomes, usePriceStreamStore } from "@/hooks/usePriceStreamConnection";

/**
 * Subscribe to live market prices via SSE and expose the latest display prices per outcome.
 * Falls back to initial SSR prices until a tick arrives.
 */
export function useLiveOutcomePrices(marketId: string, initialPrices: number[] = []) {
  const streamState = usePriceStreamStore(marketId);

  useEffect(() => {
    seedInitialOutcomes(marketId, initialPrices);
  }, [marketId, initialPrices]);

  const outcomes = useMemo(() => streamState.outcomes, [streamState.outcomes]);
  const prices = outcomes.map((p) => p?.displayPrice).map((v) => (typeof v === "number" ? v : undefined));
  const fxStale = outcomes.some((p) => p?.fxStale);

  return { prices, fxStale, outcomes, streamError: streamState.error, connected: streamState.connected };
}
