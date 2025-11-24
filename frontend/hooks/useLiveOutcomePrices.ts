import { useEffect, useState } from "react";
import { createPriceStream } from "@/lib/pricing-client";

type OutcomePrice = {
  price?: number;
  displayPrice?: number;
  fxStale?: boolean;
  updatedAt?: string;
};

/**
 * Subscribe to live market prices via SSE and expose the latest display prices per outcome.
 * Falls back to initial SSR prices until a tick arrives.
 */
export function useLiveOutcomePrices(marketId: string, initialPrices: number[] = []) {
  const [outcomes, setOutcomes] = useState<OutcomePrice[]>(
    initialPrices.map((p) => ({ price: p, displayPrice: p })),
  );
  const [streamError, setStreamError] = useState<string | null>(null);
  const [connected, setConnected] = useState<boolean>(false);

  useEffect(() => {
    setOutcomes(initialPrices.map((p) => ({ price: p, displayPrice: p })));
  }, [marketId, initialPrices]);

  useEffect(() => {
    const es = createPriceStream(marketId);
    es.onopen = () => {
      setConnected(true);
      setStreamError(null);
    };
    es.onmessage = (event: MessageEvent) => {
      try {
        const payload = JSON.parse(event.data);
        const idx = Number(payload.outcome);
        if (!Number.isInteger(idx) || idx < 0) return;
        const price = Number(payload.price);
        const displayPrice = Number(payload.display_price ?? payload.price);
        setOutcomes((prev) => {
          const next = [...prev];
          next[idx] = {
            price: Number.isFinite(price) ? price : prev[idx]?.price,
            displayPrice: Number.isFinite(displayPrice) ? displayPrice : prev[idx]?.displayPrice,
            fxStale: Boolean(payload.fx_stale),
            updatedAt: payload.timestamp,
          };
          return next;
        });
        setConnected(true);
        setStreamError(null);
      } catch {
        // ignore bad payloads
      }
    };
    es.onerror = () => {
      setStreamError("Price stream disconnected");
      setConnected(false);
      es.close();
    };
    return () => es.close();
  }, [marketId]);

  const prices = outcomes.map((p) => p?.displayPrice).map((v) => (typeof v === "number" ? v : undefined));
  const fxStale = outcomes.some((p) => p?.fxStale);

  return { prices, fxStale, outcomes, streamError, connected };
}
