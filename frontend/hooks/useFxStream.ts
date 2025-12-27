import { useEffect, useRef, useSyncExternalStore } from "react";
import {
  FX_DEFAULT_PATH,
  createFxWebSocket,
  fetchStreamerFxQuote,
  normalizeFxPath,
  shouldUseStreamerWs,
  type FxQuote,
} from "@/lib/pricing-client";

type FxStatus = "connecting" | "live" | "stale" | "error";

type FxState = {
  fx: FxQuote | null;
  error: string | null;
  status: FxStatus;
  lastUpdate: number;
  wsConnected: boolean;
  wsDelivered: boolean;
  restFallbacks: number;
  fxReceivedAt: string | null;
  ageSeconds: number | null;
};

type FxConnectionState = FxState;

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
  reconnectTimer: ReturnType<typeof setTimeout> | null;
  cleanup?: () => void;
};

const connections = new Map<string, FxConnection>();
const isTestEnv = process.env.NODE_ENV === "test" || process.env.VITEST === "true";
const unrefTimer = <T extends ReturnType<typeof setTimeout> | ReturnType<typeof setInterval>>(timer: T) => {
  (timer as unknown as { unref?: () => void }).unref?.();
  return timer;
};

const initialState: FxConnectionState = {
  fx: null,
  error: null,
  status: "connecting",
  lastUpdate: 0,
  wsConnected: false,
  wsDelivered: false,
  restFallbacks: 0,
  fxReceivedAt: null,
  ageSeconds: null,
};
const initialFxSnapshot: FxState = { ...initialState };

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
        fxReceivedAt: data.received_at ?? conn.state.fxReceivedAt ?? null,
        ageSeconds:
          typeof data.age_seconds === "number"
            ? data.age_seconds
            : data.received_at
              ? Math.max(0, (Date.now() - Date.parse(data.received_at)) / 1000)
              : conn.state.ageSeconds,
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
    // Encourage a reconnect if WS is stale or missing while REST is carrying us.
    const needsReconnect = !conn.state.wsConnected || Date.now() - conn.state.lastUpdate > 15_000 || conn.state.fx?.stale;
    if (needsReconnect) {
      conn.wsFailures = 0;
      conn.backoff = 1_000;
      if (conn.ws && conn.ws.readyState === WebSocket.OPEN) {
        conn.ws.close(1000, "refresh");
      }
      unrefTimer(setTimeout(connect, 250));
    }
  };
  if (conn.fallbackTimer) return;
  // First fetch immediately to avoid blank UI if WS is unavailable.
  runFetch().catch(() => {});
  conn.fallbackTimer = unrefTimer(setInterval(runFetch, 5_000));
}

function startConnection(path: string) {
  const normalizedPath = normalizeFxPath(path);
  const existing = connections.get(normalizedPath);
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
    reconnectTimer: null,
  };

  const cleanup = () => {
    conn.cancelled = true;
    if (conn.idleCloseTimer) {
      clearTimeout(conn.idleCloseTimer);
      conn.idleCloseTimer = null;
    }
    if (conn.reconnectTimer) {
      clearTimeout(conn.reconnectTimer);
      conn.reconnectTimer = null;
    }
    if (conn.fallbackTimer) {
      clearInterval(conn.fallbackTimer);
      conn.fallbackTimer = null;
    }
    if (conn.ws) {
      try {
        conn.ws.close(1000, "idle");
      } catch {
        // ignore
      }
      conn.ws = null;
    }
    connections.delete(normalizedPath);
  };
  conn.cleanup = cleanup;

  const scheduleReconnect = (delay: number) => {
    if (conn.reconnectTimer) {
      clearTimeout(conn.reconnectTimer);
    }
    conn.reconnectTimer = unrefTimer(
      setTimeout(() => {
        conn.reconnectTimer = null;
        connect();
      }, delay),
    );
  };

  const connect = () => {
    if (conn.cancelled) return;
    // If WS is explicitly disabled (env or after repeated failures), rely on REST-only mode.
    const wsAllowed =
      typeof window !== "undefined" &&
      shouldUseStreamerWs() &&
      "WebSocket" in window &&
      Date.now() >= conn.wsDisabledUntil;
    if (!wsAllowed) {
      setState(conn, { wsConnected: false, status: conn.state.fx ? conn.state.status : "stale" });
      return;
    }
    try {
      const ws = createFxWebSocket(normalizedPath);
      if (!ws) {
        conn.wsDisabledUntil = Date.now() + 60_000;
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
            received_at: typeof payload.received_at === "string" ? payload.received_at : undefined,
            age_seconds: typeof payload.age_seconds === "number" ? payload.age_seconds : undefined,
            source: typeof payload.source === "string" ? payload.source : undefined,
          };
          setState(conn, {
            fx: nextFx,
            status: nextFx.stale ? "stale" : "live",
            error: null,
            lastUpdate: Date.now(),
            wsDelivered: true,
            restFallbacks: 0,
            fxReceivedAt: nextFx.received_at ?? conn.state.fxReceivedAt ?? null,
            ageSeconds:
              typeof nextFx.age_seconds === "number"
                ? nextFx.age_seconds
                : nextFx.received_at
                  ? Math.max(0, (Date.now() - Date.parse(nextFx.received_at)) / 1000)
                  : conn.state.ageSeconds,
          });
        } catch (err) {
          setState(conn, { error: (err as Error).message, status: "error" });
          console.error("FX stream error", err);
        }
      };
      ws.onerror = () => {
        if (conn.cancelled) return;
        setState(conn, { wsConnected: false, status: "stale", error: "FX socket error" });
        try {
          ws.close();
        } catch {
          // ignore
        }
      };
      ws.onclose = (evt) => {
        if (conn.cancelled) return;
        const delay = Math.min(conn.backoff, 10_000);
        // Treat suspension/closure as stale and let REST fill in.
        setState(conn, { wsConnected: false, status: "stale" });
        if (evt?.reason?.toLowerCase().includes("suspension")) {
          console.warn("FX socket closed due to suspension; falling back to REST");
        } else {
          console.warn("FX socket closed, reconnecting", { delay });
        }
        conn.wsFailures += 1;
        if (conn.wsFailures >= 5) {
          conn.wsDisabledUntil = Date.now() + 60_000;
          conn.wsFailures = 0;
          conn.backoff = 1_000;
          scheduleReconnect(60_000);
          return;
        }
        conn.backoff = Math.min(delay * 2, 30_000);
        scheduleReconnect(delay);
      };
    } catch (err) {
      setState(conn, { wsConnected: false, error: (err as Error).message, status: "stale" });
      conn.wsDisabledUntil = Date.now() + 30_000;
      console.error("FX stream init failed; relying on REST", err);
    }
  };

  startFallback(path, conn, connect);
  connect();
  connections.set(normalizedPath, conn);
  return conn;
}

function subscribeToConnection(path: string, onChange: () => void) {
  const conn = startConnection(path);
  if (conn.idleCloseTimer) {
    clearTimeout(conn.idleCloseTimer);
    conn.idleCloseTimer = null;
  }
  conn.subscribers.add(onChange);
  return () => {
    conn.subscribers.delete(onChange);
    // Keep the connection warm for reuse across pages/routes; we intentionally do not close the socket on unsubscribe.
    if (conn.subscribers.size === 0 && isTestEnv) {
      if (conn.idleCloseTimer) {
        clearTimeout(conn.idleCloseTimer);
      }
      conn.idleCloseTimer = unrefTimer(
        setTimeout(() => {
          if (conn.subscribers.size > 0) return;
          conn.cleanup?.();
        }, 50),
      );
    }
  };
}

function getSnapshot(path: string): FxState {
  const conn = connections.get(path);
  if (!conn) return initialFxSnapshot;
  return conn.state;
}

export function useFxStream(path = FX_DEFAULT_PATH): FxState {
  const normalized = normalizeFxPath(path);
  const pathRef = useRef(normalized);
  pathRef.current = normalized;

  const subscribe = (onStoreChange: () => void) => subscribeToConnection(pathRef.current, onStoreChange);
  const getSnap = () => getSnapshot(pathRef.current);

  const state = useSyncExternalStore(subscribe, getSnap, () => initialFxSnapshot);

  useEffect(() => {
    // Ensure connection starts when path changes.
    startConnection(normalized);
  }, [normalized]);

  return state;
}
