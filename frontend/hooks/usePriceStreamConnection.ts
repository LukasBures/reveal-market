import { useEffect, useSyncExternalStore } from "react";
import {
  createMarketStream,
  createMarketWebSocket,
  priceStreamsDisabled,
  shouldUseStreamerWs,
} from "@/lib/pricing-client";

export type PricePoint = {
  timestamp: string;
  price: number;
  display_price: number;
  fx_stale?: boolean;
};

export type OutcomePrice = {
  price?: number;
  displayPrice?: number;
  fxStale?: boolean;
  updatedAt?: string;
  bestBid?: number;
  bestAsk?: number;
  status?: string | null;
};

type StreamState = {
  connected: boolean;
  error: string | null;
  outcomes: OutcomePrice[];
  histories: Record<number, PricePoint[]>;
  trades: Array<{ price?: number; size?: number; side?: string; timestamp: string }>;
  tickSize?: number;
  status?: string | null;
};

type StreamConnection = {
  state: StreamState;
  subscribers: Set<() => void>;
  es: EventSource | null;
  ws: WebSocket | null;
  backoff: number;
  cancelled: boolean;
  transport: "ws" | "sse" | null;
  wsAttempts: number;
  wsDisabled: boolean;
  idleCloseTimer: ReturnType<typeof setTimeout> | null;
};

const connections = new Map<string, StreamConnection>();
const normalizeTokens = (tokenIds: string[]) =>
  tokenIds
    .map((t) => t.trim())
    .filter(Boolean)
    .sort();

const initialState: StreamState = {
  connected: false,
  error: null,
  outcomes: [],
  histories: {},
  trades: [],
  tickSize: undefined,
  status: null,
};

function notify(conn: StreamConnection) {
  conn.subscribers.forEach((cb) => cb());
}

function setState(conn: StreamConnection, patch: Partial<StreamState>) {
  conn.state = { ...conn.state, ...patch };
  notify(conn);
}

function updateOutcome(conn: StreamConnection, outcome: number, updater: (prev: OutcomePrice) => OutcomePrice) {
  const outcomes = [...conn.state.outcomes];
  while (outcomes.length <= outcome) {
    outcomes.push({});
  }
  outcomes[outcome] = updater(outcomes[outcome] ?? {});
  setState(conn, { outcomes });
}

function appendHistory(conn: StreamConnection, outcome: number, point: PricePoint) {
  const histories = { ...conn.state.histories };
  const prev = histories[outcome] ?? [];
  histories[outcome] = [...prev.slice(-199), point];
  setState(conn, { histories });
}

function appendTrade(conn: StreamConnection, trade: { price?: number; size?: number; side?: string; timestamp: string }) {
  const trades = [...conn.state.trades.slice(-49), trade];
  setState(conn, { trades });
}

function startConnection(marketId: string, tokenIds: string[] = []) {
  const normalizedTokens = normalizeTokens(tokenIds);
  const key = `${marketId}|${normalizedTokens.join(",")}`;
  const existing = connections.get(key);
  if (existing) return existing;

  const conn: StreamConnection = {
    state: { ...initialState },
    subscribers: new Set(),
    es: null,
    ws: null,
    backoff: 1_000,
    cancelled: false,
    transport: null,
    wsAttempts: 0,
    wsDisabled: !shouldUseStreamerWs(),
    idleCloseTimer: null,
  };

  const handlePayload = (raw: string) => {
    try {
      const payload = JSON.parse(raw);
      const payloadType = (payload.type || payload.event_type || "").toString().toLowerCase();
      if (payloadType === "trade") {
        appendTrade(conn, {
          price: payload.price !== undefined ? Number(payload.price) : undefined,
          size: payload.size !== undefined ? Number(payload.size) : undefined,
          side: payload.side,
          timestamp: payload.timestamp,
        });
        return;
      }
      if (payloadType === "tick_size") {
        const tickSize = Number(payload.tick_size);
        if (Number.isFinite(tickSize)) {
          setState(conn, { tickSize });
        }
        return;
      }
      if (payloadType === "book") {
        const bestBid = payload.display_best_bid !== undefined ? Number(payload.display_best_bid) : undefined;
        const bestAsk = payload.display_best_ask !== undefined ? Number(payload.display_best_ask) : undefined;
        updateOutcome(conn, 0, (prev) => ({ ...prev, bestBid, bestAsk }));
        updateOutcome(conn, 1, (prev) => ({ ...prev, bestBid, bestAsk }));
        return;
      }
      const outcome = Number(payload.outcome);
      if (!Number.isInteger(outcome) || outcome < 0) return;
      const price = Number(payload.price);
      const displayPrice = Number(payload.display_price ?? payload.price);
      if (!Number.isFinite(price)) return;
      const point: PricePoint = {
        timestamp: payload.timestamp,
        price,
        display_price: Number.isFinite(displayPrice) ? displayPrice : price,
        fx_stale: payload.fx_stale,
      };
      updateOutcome(conn, outcome, () => ({
        price,
        displayPrice: Number.isFinite(displayPrice) ? displayPrice : price,
        fxStale: Boolean(payload.fx_stale),
        updatedAt: payload.timestamp,
        bestBid: payload.display_best_bid !== undefined ? Number(payload.display_best_bid) : undefined,
        bestAsk: payload.display_best_ask !== undefined ? Number(payload.display_best_ask) : undefined,
        status: payload.status,
      }));
      appendHistory(conn, outcome, point);
      setState(conn, { connected: true, error: null });
    } catch (err) {
      setState(conn, { error: (err as Error).message });
    }
  };

  const connectSse = () => {
    if (conn.cancelled) return;
    try {
      const es = createMarketStream(marketId, normalizedTokens);
      conn.es = es;
      conn.transport = "sse";
      es.onopen = () => {
        setState(conn, { connected: true, error: null });
        conn.backoff = 1_000;
        // Attempt to upgrade back to WS after a short delay to keep WS-first.
        setTimeout(() => {
          if (!conn.cancelled && !conn.ws) {
            connectWs();
          }
        }, 15_000);
      };
      es.onmessage = (event: MessageEvent) => {
        handlePayload(event.data);
      };
      es.onerror = () => {
        setState(conn, { connected: false, error: "Price stream disconnected" });
        es.close();
        setTimeout(connectWs, Math.min(conn.backoff, 15_000));
        conn.backoff = Math.min(conn.backoff * 2, 30_000);
      };
    } catch (err) {
      setState(conn, { error: (err as Error).message, connected: false });
      setTimeout(connectWs, Math.min(conn.backoff, 15_000));
      conn.backoff = Math.min(conn.backoff * 2, 30_000);
    }
  };

  const connectWs = () => {
    if (conn.cancelled) return;
    if (conn.wsDisabled || !shouldUseStreamerWs()) {
      connectSse();
      return;
    }
    try {
      const ws = createMarketWebSocket(marketId, normalizedTokens);
      if (!ws) {
        // If WS can't be constructed (e.g., mixed content), fall back to SSE.
        connectSse();
        return;
      }
      conn.ws = ws;
      conn.transport = "ws";
      ws.onopen = () => {
        setState(conn, { connected: true, error: null });
        conn.backoff = 1_000;
        conn.wsAttempts = 0;
        if (conn.es) {
          conn.es.close();
          conn.es = null;
        }
      };
      ws.onmessage = (event: MessageEvent) => {
        const data = typeof event.data === "string" ? event.data : "";
        handlePayload(data);
      };
      ws.onerror = () => {
        setState(conn, { connected: false, error: "Price stream disconnected" });
        ws.close();
        conn.wsAttempts += 1;
        if (conn.wsAttempts >= 2) {
          conn.wsDisabled = true;
          connectSse();
          return;
        }
        connectSse();
      };
      ws.onclose = () => {
        setState(conn, { connected: false, error: "Price stream disconnected" });
        conn.wsAttempts += 1;
        if (conn.wsAttempts >= 2) {
          conn.wsDisabled = true;
          connectSse();
          return;
        }
        connectSse();
      };
    } catch (err) {
      setState(conn, { error: (err as Error).message, connected: false });
      setTimeout(connectWs, Math.min(conn.backoff, 15_000));
      conn.backoff = Math.min(conn.backoff * 2, 30_000);
    }
  };

  if (shouldUseStreamerWs()) {
    connectWs();
  } else {
    connectSse();
  }
  connections.set(key, conn);
  return conn;
}

function subscribe(marketId: string, tokenIds: string[], onChange: () => void) {
  const normalizedTokens = normalizeTokens(tokenIds);
  const key = `${marketId}|${normalizedTokens.join(",")}`;
  const conn = startConnection(marketId, normalizedTokens);
  if (conn.idleCloseTimer) {
    clearTimeout(conn.idleCloseTimer);
    conn.idleCloseTimer = null;
  }
  conn.subscribers.add(onChange);
  return () => {
    conn.subscribers.delete(onChange);
    if (conn.subscribers.size === 0) {
      if (conn.idleCloseTimer) {
        clearTimeout(conn.idleCloseTimer);
      }
      conn.idleCloseTimer = setTimeout(() => {
        if (conn.subscribers.size > 0) return;
        conn.cancelled = true;
        if (conn.es) conn.es.close();
        if (conn.ws && conn.ws.readyState !== WebSocket.CLOSED) conn.ws.close();
        connections.delete(key);
      }, 30_000);
    }
  };
}

function snapshot(marketId: string, tokenIds: string[]): StreamState {
  const key = `${marketId}|${normalizeTokens(tokenIds).join(",")}`;
  const conn = connections.get(key);
  if (!conn) return { ...initialState };
  return conn.state;
}

export function usePriceStreamStore(marketId: string, tokenIds: string[] = []): StreamState {
  if (priceStreamsDisabled) {
    return initialState;
  }
  const subscribeFn = (onStoreChange: () => void) => subscribe(marketId, tokenIds, onStoreChange);
  const getSnapshot = () => snapshot(marketId, tokenIds);
  return useSyncExternalStore(subscribeFn, getSnapshot, getSnapshot);
}

export function seedHistory(marketId: string, outcome: number, points: PricePoint[], tokenIds: string[] = []) {
  const conn = startConnection(marketId, tokenIds);
  if (!points.length) return;
  const histories = { ...conn.state.histories };
  histories[outcome] = points.slice(-200);
  setState(conn, { histories });
}

export function seedInitialOutcomes(marketId: string, prices: number[], tokenIds: string[] = []) {
  if (!prices.length) return;
  const conn = startConnection(marketId, tokenIds);
  const hasData = conn.state.outcomes.some((p) => p.price !== undefined);
  if (hasData) return;
  const outcomes = prices.map((p) => ({ price: p, displayPrice: p }));
  setState(conn, { outcomes });
}
