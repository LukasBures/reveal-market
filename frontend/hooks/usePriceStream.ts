import { useEffect, useMemo, useState } from "react";
import { fetchPriceHistory } from "@/lib/pricing-client";
import { seedHistory, usePriceStreamStore } from "@/hooks/usePriceStreamConnection";

export function usePriceStream(marketId: string, outcome = 0) {
  const [historyLoaded, setHistoryLoaded] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const streamState = usePriceStreamStore(marketId);

  useEffect(() => {
    setHistoryLoaded(false);
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchPriceHistory(marketId, outcome, 200);
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
        );
        setHistoryLoaded(true);
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [marketId, outcome]);

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
