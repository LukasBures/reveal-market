import { useEffect, useRef, useSyncExternalStore } from "react";
import { createFxWebSocket, fetchStreamerFxQuote, type FxQuote } from "@/lib/pricing-client";

type FxState = {
  fx: FxQuote | null;
  error: string | null;
  status: "connecting" | "live" | "stale" | "error";
};

type FxConnectionState = {
  fx: FxQuote | null;
  error: string | null;
  status: FxState["status"];
  lastUpdate: number;
  wsConnected: boolean;
  wsDelivered: boolean;
  restFallbacks: number;
};

type FxConnection = {
  state: FxConnectionState;
  subscribers: Set<() => void>;
  ws: WebSocket | null;
  backoff: number;
  startTs: number;
  fallbackTimer: ReturnType<typeof setInterval> | null;
  cancelled: boolean;
};

const connections = new Map<string, FxConnection>();

const initialState: FxConnectionState = {
  fx: null,
  error: null,
  status: "connecting",
  lastUpdate: 0,
  wsConnected: false,
  wsDelivered: false,
  restFallbacks: 0,
};

function notify(conn: FxConnection) {
  conn.subscribers.forEach((cb) => cb());
}

function setState(conn: FxConnection, patch: Partial<FxConnectionState>) {
  conn.state = { ...conn.state, ...patch };
  notify(conn);
}

function startFallback(path: string, conn: FxConnection, connect: () => void) {
  if (conn.fallbackTimer) return;
  conn.fallbackTimer = setInterval(async () => {
    if (conn.cancelled) return;
    const age = Date.now() - conn.state.lastUpdate;
    const sinceStart = Date.now() - conn.startTs;
    const wsHealthy = conn.state.wsConnected && conn.state.wsDelivered && !conn.state.fx?.stale && age < 15_000;
    if (wsHealthy) return;
    if (!conn.state.wsDelivered && sinceStart < 5_000) return;
    try {
      const data = await fetchStreamerFxQuote(path);
      setState(conn, {
        fx: data,
        status: data.stale ? "stale" : "live",
        error: null,
        lastUpdate: Date.now(),
        restFallbacks: conn.state.restFallbacks + 1,
      });
      if (data.stale) {
        console.warn("FX HTTP fallback stale", data);
      }
    } catch (err) {
      setState(conn, {
        error: (err as Error).message,
        status: "error",
        restFallbacks: conn.state.restFallbacks + 1,
      });
      console.error("FX HTTP fallback failed", err);
    }
    if (
      conn.state.restFallbacks >= 3 &&
      (!conn.state.wsConnected || Date.now() - conn.state.lastUpdate > 15_000 || conn.state.fx?.stale)
    ) {
      setState(conn, { restFallbacks: 0 });
      conn.backoff = 1_000;
      if (conn.ws && conn.ws.readyState === WebSocket.OPEN) {
        conn.ws.close();
      }
      setTimeout(connect, 200);
    }
  }, 5_000);
}

function startConnection(path: string) {
  const existing = connections.get(path);
  if (existing) return existing;

  const conn: FxConnection = {
    state: { ...initialState },
    subscribers: new Set(),
    ws: null,
    backoff: 1_000,
    startTs: Date.now(),
    fallbackTimer: null,
    cancelled: false,
  };

  const connect = () => {
    if (conn.cancelled) return;
    try {
      const ws = createFxWebSocket(path);
      conn.ws = ws;
      ws.onopen = () => {
        // Keep a single shared WS per path; reset backoff on success.
        setState(conn, { wsConnected: true, status: conn.state.status === "error" ? "connecting" : conn.state.status });
        conn.backoff = 1_000;
      };
      ws.onmessage = (event) => {
        if (conn.cancelled) return;
        try {
          const payload = JSON.parse(event.data);
          const nextFx: FxQuote = {
            zen_usd: Number(payload.zen_usd),
            raw_zen_usd: payload.raw_zen_usd ? Number(payload.raw_zen_usd) : undefined,
            stale: Boolean(payload.stale),
          };
          setState(conn, {
            fx: nextFx,
            status: nextFx.stale ? "stale" : "live",
            error: null,
            lastUpdate: Date.now(),
            wsDelivered: true,
          });
        } catch (err) {
          setState(conn, { error: (err as Error).message, status: "error" });
          console.error("FX stream error", err);
        }
      };
      ws.onerror = () => {
        setState(conn, { wsConnected: false, status: "error", error: "FX socket error" });
      };
      ws.onclose = () => {
        if (conn.cancelled) return;
        const delay = Math.min(conn.backoff, 10_000);
        setState(conn, { wsConnected: false, status: "error" });
        console.warn("FX socket closed, reconnecting", { delay });
        conn.backoff = delay * 2;
        setTimeout(connect, delay);
      };
    } catch (err) {
      setState(conn, { wsConnected: false, error: (err as Error).message, status: "error" });
      console.error("FX stream init failed", err);
    }
  };

  startFallback(path, conn, connect);
  connect();
  connections.set(path, conn);
  return conn;
}

function subscribeToConnection(path: string, onChange: () => void) {
  const conn = startConnection(path);
  conn.subscribers.add(onChange);
  return () => {
    conn.subscribers.delete(onChange);
    if (conn.subscribers.size === 0) {
      conn.cancelled = true;
      if (conn.fallbackTimer) clearInterval(conn.fallbackTimer);
      if (conn.ws && conn.ws.readyState !== WebSocket.CLOSED) {
        conn.ws.close();
      }
      connections.delete(path);
    }
  };
}

function getSnapshot(path: string): FxState {
  const conn = connections.get(path);
  if (!conn) return { fx: null, error: null, status: "connecting" };
  return { fx: conn.state.fx, error: conn.state.error, status: conn.state.status };
}

export function useFxStream(path = "/fx/zen-usdc"): FxState {
  const pathRef = useRef(path);
  pathRef.current = path;

  const subscribe = (onStoreChange: () => void) => subscribeToConnection(pathRef.current, onStoreChange);
  const getSnap = () => getSnapshot(pathRef.current);

  const state = useSyncExternalStore(subscribe, getSnap, getSnap);

  useEffect(() => {
    // Ensure connection starts when path changes.
    startConnection(path);
  }, [path]);

  return state;
}
