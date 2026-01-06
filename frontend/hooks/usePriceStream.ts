import { useEffect, useMemo, useState } from "react";
import { fetchPriceHistory, type PriceHistoryInterval } from "@/lib/pricing-client";
import { seedHistory, usePriceStreamStore } from "@/hooks/usePriceStreamConnection";

export type PriceHistoryRange = "1H" | "24H" | "7D" | "MAX";

const RANGE_CONFIG: Record<PriceHistoryRange, { interval: PriceHistoryInterval; fidelity: number }> = {
  "1H": { interval: "1h", fidelity: 1 },
  "24H": { interval: "1d", fidelity: 5 },
  "7D": { interval: "1w", fidelity: 30 },
  "MAX": { interval: "max", fidelity: 240 },
};

export function usePriceStream(
  marketId: string,
  outcome = 0,
  tokenIds: string[] = [],
  range: PriceHistoryRange = "24H",
) {
  const [historyLoaded, setHistoryLoaded] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const streamState = usePriceStreamStore(marketId, tokenIds);
  const tokenId = tokenIds[outcome];
  const historyConfig = RANGE_CONFIG[range] ?? RANGE_CONFIG["24H"];

  useEffect(() => {
    setHistoryLoaded(false);
    setError(null);
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchPriceHistory(marketId, outcome, {
          interval: historyConfig.interval,
          fidelity: historyConfig.fidelity,
          tokenId,
        });
        if (cancelled) return;
        seedHistory(
          marketId,
          outcome,
          data
            .map((entry) => ({
              timestamp: entry.timestamp,
              price: Number(entry.price),
              display_price: Number(entry.display_price),
              fx_stale: entry.fx_stale,
            }))
            .filter((p) => Number.isFinite(p.price)),
          tokenIds,
        );
        setHistoryLoaded(true);
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [marketId, outcome, tokenId, historyConfig.interval, historyConfig.fidelity, tokenIds]);

  const chartPoints = useMemo(
    () =>
      (streamState.histories[outcome] ?? []).map((point) => ({
        x: new Date(point.timestamp).getTime(),
        y: point.display_price || point.price,
        fx_stale: point.fx_stale,
        timestamp: point.timestamp,
      })),
    [streamState.histories, outcome],
  );

  const combinedError = error || streamState.error;

  return { history: chartPoints, error: combinedError, connected: streamState.connected, historyLoaded };
}
