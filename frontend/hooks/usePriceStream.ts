import { useMemo } from "react";
import { usePriceStreamStore } from "@/hooks/usePriceStreamConnection";

export type PriceHistoryRange = "1H" | "24H" | "7D" | "MAX";

export function usePriceStream(
  marketId: string,
  outcome = 0,
  tokenIds: string[] = [],
) {
  const streamState = usePriceStreamStore(marketId, tokenIds);

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

  const combinedError = streamState.error;

  return { history: chartPoints, error: combinedError, connected: streamState.connected, historyLoaded: true };
}
