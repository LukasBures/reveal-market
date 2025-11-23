import { useEffect, useMemo, useState } from "react";
import { createPriceStream, fetchPriceHistory } from "@/lib/pricing-client";

type PricePoint = {
  timestamp: string;
  price: number;
  display_price: number;
  fx_stale?: boolean;
};

export function usePriceStream(marketId: string, outcome = 0) {
  const [history, setHistory] = useState<PricePoint[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const data = await fetchPriceHistory(marketId, outcome, 200);
        if (cancelled) return;
        setHistory(
          data
            .map((entry) => ({
              timestamp: entry.timestamp,
              price: Number(entry.price),
              display_price: Number(entry.display_price),
              fx_stale: entry.fx_stale,
            }))
            .filter((p) => Number.isFinite(p.price)),
        );
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [marketId, outcome]);

  useEffect(() => {
    const es = createPriceStream(marketId);
    const handler = (event: MessageEvent) => {
      try {
        const payload = JSON.parse(event.data);
        if (Number(payload.outcome) !== outcome) return;
        const point: PricePoint = {
          timestamp: payload.timestamp,
          price: Number(payload.price),
          display_price: Number(payload.display_price),
          fx_stale: payload.fx_stale,
        };
        if (!Number.isFinite(point.price)) return;
        setHistory((prev) => [...prev.slice(-199), point]);
      } catch (err) {
        setError((err as Error).message);
      }
    };
    es.onmessage = handler;
    es.onerror = () => {
      setError("Price stream disconnected");
      es.close();
    };
    return () => {
      es.close();
    };
  }, [marketId, outcome]);

  const chartPoints = useMemo(
    () =>
      history.map((point) => ({
        x: new Date(point.timestamp).getTime(),
        y: point.display_price || point.price,
        fx_stale: point.fx_stale,
      })),
    [history],
  );

  return { history: chartPoints, error };
}
