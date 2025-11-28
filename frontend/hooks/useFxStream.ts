import { useEffect, useRef, useSyncExternalStore } from "react";
import { createFxWebSocket, fetchStreamerFxQuote, shouldUseStreamerWs, type FxQuote } from "@/lib/pricing-client";

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
  wsFailures: number;
  wsDisabledUntil: number;
  startTs: number;
  fallbackTimer: ReturnType<typeof setInterval> | null;
  cancelled: boolean;
  idleCloseTimer: ReturnType<typeof setTimeout> | null;
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
const initialFxSnapshot: FxState = { fx: null, error: null, status: "connecting" };

function notify(conn: FxConnection) {
  conn.subscribers.forEach((cb) => cb());
}

function setState(conn: FxConnection, patch: Partial<FxConnectionState>) {
  conn.state = { ...conn.state, ...patch };
  notify(conn);
}

function startFallback(path: string, conn: FxConnection, connect: () => void) {
  const runFetch = async () => {
    if (conn.cancelled || conn.subscribers.size === 0) return;
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
  };
  if (conn.fallbackTimer) return;
  // First fetch immediately to avoid blank UI if WS is unavailable.
  runFetch().catch(() => {});
  conn.fallbackTimer = setInterval(runFetch, 5_000);
}

function startConnection(path: string) {
  const existing = connections.get(path);
  if (existing) return existing;

  const conn: FxConnection = {
    state: { ...initialState },
    subscribers: new Set(),
    ws: null,
    backoff: 1_000,
    wsFailures: 0,
    wsDisabledUntil: 0,
    startTs: Date.now(),
    fallbackTimer: null,
    cancelled: false,
    idleCloseTimer: null,
  };

  const connect = () => {
    if (conn.cancelled) return;
    // If WS is explicitly disabled (env or after repeated failures), rely on REST-only mode.
    const wsAllowed =
      typeof window !== "undefined" && shouldUseStreamerWs() && "WebSocket" in window && conn.wsDisabledUntil !== Infinity;
    if (!wsAllowed) {
      setState(conn, { wsConnected: false, status: conn.state.fx ? conn.state.status : "stale" });
      return;
    }
    if (Date.now() < conn.wsDisabledUntil) {
      setTimeout(connect, 5_000);
      return;
    }
    try {
      const ws = createFxWebSocket(path);
      if (!ws) {
        conn.wsDisabledUntil = Infinity;
        setState(conn, { wsConnected: false, status: conn.state.fx ? conn.state.status : "stale" });
        return;
      }
      conn.ws = ws;
      ws.onopen = () => {
        // Keep a single shared WS per path; reset backoff on success.
        setState(conn, { wsConnected: true, status: conn.state.status === "error" ? "connecting" : conn.state.status });
        conn.backoff = 1_000;
        conn.wsFailures = 0;
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
        setState(conn, { wsConnected: false, status: "stale", error: "FX socket error" });
      };
      ws.onclose = (evt) => {
        if (conn.cancelled) return;
        const delay = Math.min(conn.backoff, 10_000);
        // Treat suspension/closure as stale and let REST fill in.
        setState(conn, { wsConnected: false, status: "stale" });
        if (evt && typeof evt.reason === "string" && evt.reason.toLowerCase().includes("suspension")) {
          console.warn("FX socket closed due to suspension; falling back to REST");
        } else {
          console.warn("FX socket closed, reconnecting", { delay });
        }
        conn.wsFailures += 1;
        // After a couple failures, stop trying WS entirely and rely on REST to keep UI working.
        if (conn.wsFailures >= 2) {
          conn.wsDisabledUntil = Infinity;
          return;
        }
        if (conn.wsFailures >= 3) {
          conn.wsDisabledUntil = Date.now() + 60_000;
          conn.wsFailures = 0;
          return;
        }
        conn.backoff = delay * 2;
        setTimeout(connect, delay);
      };
    } catch (err) {
      setState(conn, { wsConnected: false, error: (err as Error).message, status: "stale" });
      conn.wsDisabledUntil = Date.now() + 60_000;
      console.error("FX stream init failed; relying on REST", err);
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
    // Keep the connection warm for reuse across pages/routes; we intentionally do not close the socket on unsubscribe.
  };
}

function getSnapshot(path: string): FxState {
  const conn = connections.get(path);
  if (!conn) return initialFxSnapshot;
  return conn.state as FxState;
}

export function useFxStream(path = "/fx/zen-usdc"): FxState {
  const pathRef = useRef(path);
  pathRef.current = path;

  const subscribe = (onStoreChange: () => void) => subscribeToConnection(pathRef.current, onStoreChange);
  const getSnap = () => getSnapshot(pathRef.current);

  const state = useSyncExternalStore(subscribe, getSnap, () => initialFxSnapshot);

  useEffect(() => {
    // Ensure connection starts when path changes.
    startConnection(path);
  }, [path]);

  return state;
}
