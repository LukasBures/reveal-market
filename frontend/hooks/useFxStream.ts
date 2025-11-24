import { useEffect, useRef, useState } from "react";
import { createFxWebSocket, fetchStreamerFxQuote, type FxQuote } from "@/lib/pricing-client";

type FxState = {
  fx: FxQuote | null;
  error: string | null;
  status: "connecting" | "live" | "stale" | "error";
};

/**
 * Subscribe to FX via WS with backoff + HTTP fallback.
 */
export function useFxStream(path = "/fx/zen-usdc"): FxState {
  const [fx, setFx] = useState<FxQuote | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<FxState["status"]>("connecting");
  const lastUpdateRef = useRef<number>(0);
  const backoffRef = useRef<number>(1000);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let cancelled = false;
    const connect = () => {
      if (cancelled) return;
      try {
        const ws = createFxWebSocket(path);
        wsRef.current = ws;
        ws.onopen = () => {
          backoffRef.current = 1000;
          setStatus((prev) => (prev === "error" ? "connecting" : prev));
        };
        ws.onmessage = (event) => {
          if (cancelled) return;
          try {
            const payload = JSON.parse(event.data);
            const nextFx: FxQuote = {
              zen_usd: Number(payload.zen_usd),
              raw_zen_usd: payload.raw_zen_usd ? Number(payload.raw_zen_usd) : undefined,
              stale: Boolean(payload.stale),
            };
            lastUpdateRef.current = Date.now();
            setFx(nextFx);
            setStatus(nextFx.stale ? "stale" : "live");
            setError(null);
          } catch (err) {
            setError((err as Error).message);
            setStatus("error");
          }
        };
        ws.onerror = () => {
          setStatus("error");
          setError("FX socket error");
        };
        ws.onclose = () => {
          if (cancelled) return;
          setStatus("error");
          const delay = Math.min(backoffRef.current, 10_000);
          backoffRef.current = delay * 2;
          setTimeout(connect, delay);
        };
      } catch (err) {
        setError((err as Error).message);
        setStatus("error");
      }
    };

    const fallbackPoll = setInterval(async () => {
      if (cancelled) return;
      const age = Date.now() - lastUpdateRef.current;
      if (age < 10_000 && fx && !fx.stale) return;
      try {
        const data = await fetchStreamerFxQuote(path);
        lastUpdateRef.current = Date.now();
        setFx(data);
        setStatus(data.stale ? "stale" : "live");
        setError(null);
      } catch (err) {
        setError((err as Error).message);
        setStatus("error");
      }
    }, 5_000);

    connect();
    return () => {
      cancelled = true;
      clearInterval(fallbackPoll);
      if (wsRef.current && wsRef.current.readyState !== WebSocket.CLOSED) {
        wsRef.current.close();
      }
    };
  }, [path]);

  return { fx, error, status };
}
