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
  depthBids?: Array<{ price?: number; size?: number }>;
  depthAsks?: Array<{ price?: number; size?: number }>;
};

type StreamState = {
  connected: boolean;
  error: string | null;
  outcomes: OutcomePrice[];
  histories: Record<number, PricePoint[]>;
  trades: Array<{ price?: number; size?: number; side?: string; timestamp: string }>;
  tickSize?: number;
  status?: string | null;
  transport: "ws" | "sse" | null;
  lastUpdated?: string | null;
};

type StreamConnection = {
  state: StreamState;
  subscribers: Set<() => void>;
  ws: WebSocket | null;
  sse: EventSource | null;
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
  transport: null,
  lastUpdated: null,
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
    ws: null,
    sse: null,
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
        setState(conn, { lastUpdated: payload.timestamp ?? new Date().toISOString() });
        return;
      }
      if (payloadType === "tick_size") {
        const tickSize = Number(payload.tick_size);
        if (Number.isFinite(tickSize)) {
          setState(conn, { tickSize, lastUpdated: payload.timestamp ?? new Date().toISOString() });
        }
        return;
      }
      if (payloadType === "book") {
        const bestBid = payload.display_best_bid !== undefined ? Number(payload.display_best_bid) : undefined;
        const bestAsk = payload.display_best_ask !== undefined ? Number(payload.display_best_ask) : undefined;
        const targetOutcome =
          Number.isInteger(Number(payload.outcome)) && Number(payload.outcome) >= 0 ? Number(payload.outcome) : null;
        const totalOutcomes = Math.max(conn.state.outcomes.length || 0, normalizedTokens.length || 0, 2);
        const depthBids =
          Array.isArray(payload.depth_bids) || Array.isArray(payload.depthBids) ? (payload.depth_bids || payload.depthBids) : [];
        const depthAsks =
          Array.isArray(payload.depth_asks) || Array.isArray(payload.depthAsks) ? (payload.depth_asks || payload.depthAsks) : [];
        const parsedDepth = (entries: any[]) =>
          entries
            .filter(Boolean)
            .map((entry) => ({
              price:
                entry && typeof entry.price !== "undefined"
                  ? Number(entry.price)
                  : entry && typeof entry.Price !== "undefined"
                    ? Number(entry.Price)
                    : undefined,
              size:
                entry && typeof entry.size !== "undefined"
                  ? Number(entry.size)
                  : entry && typeof entry.Size !== "undefined"
                    ? Number(entry.Size)
                    : undefined,
            }))
            .filter((d) => Number.isFinite(d.price));
        if (targetOutcome !== null) {
          updateOutcome(conn, targetOutcome, (prev) => ({
            ...prev,
            bestBid,
            bestAsk,
            depthBids: parsedDepth(depthBids),
            depthAsks: parsedDepth(depthAsks),
          }));
        } else {
          for (let i = 0; i < totalOutcomes; i += 1) {
            updateOutcome(conn, i, (prev) => ({
              ...prev,
              bestBid,
              bestAsk,
              depthBids: parsedDepth(depthBids),
              depthAsks: parsedDepth(depthAsks),
            }));
          }
        }
        setState(conn, { lastUpdated: payload.timestamp ?? new Date().toISOString() });
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
      setState(conn, { connected: true, error: null, lastUpdated: payload.timestamp ?? new Date().toISOString() });
    } catch (err) {
      setState(conn, { error: (err as Error).message });
    }
  };

  function connectSse() {
    if (conn.cancelled || typeof EventSource === "undefined" || typeof createMarketStream !== "function") return;
    if (conn.sse) return;
    try {
      const es = createMarketStream(marketId, normalizedTokens);
      if (!es) return;
      conn.sse = es;
      conn.transport = "sse";
      es.onopen = () => {
        setState(conn, { connected: true, error: null, transport: "sse" });
      };
      es.onmessage = (event: MessageEvent) => {
        const data = typeof event.data === "string" ? event.data : "";
        handlePayload(data);
      };
      es.onerror = () => {
        setState(conn, { connected: false, error: "Price stream (SSE) disconnected" });
      };
    } catch (err) {
      setState(conn, { error: (err as Error).message, connected: false });
    }
  }

  function connectWs() {
    if (conn.cancelled) return;
    if (conn.wsDisabled || !shouldUseStreamerWs()) {
      connectSse();
      return;
    }
    try {
      const ws = createMarketWebSocket(marketId, normalizedTokens);
      if (!ws) {
        conn.wsDisabled = true;
        connectSse();
        return;
      }
      conn.ws = ws;
      conn.transport = "ws";
      ws.onopen = () => {
        setState(conn, { connected: true, error: null, transport: "ws" });
        conn.backoff = 1_000;
        conn.wsAttempts = 0;
        conn.wsDisabled = false;
        if (conn.sse) {
          conn.sse.close();
          conn.sse = null;
        }
      };
      ws.onmessage = (event: MessageEvent) => {
        const data = typeof event.data === "string" ? event.data : "";
        handlePayload(data);
      };
      ws.onerror = () => {
        setState(conn, { connected: false, error: "Price stream disconnected", transport: conn.transport ?? "ws" });
        conn.ws = null;
        conn.wsAttempts += 1;
        connectSse();
        scheduleReconnect();
      };
      ws.onclose = () => {
        setState(conn, { connected: false, error: "Price stream disconnected", transport: conn.transport ?? "ws" });
        conn.ws = null;
        conn.wsAttempts += 1;
        if (conn.wsAttempts >= 2) {
          conn.wsDisabled = true;
        }
        connectSse();
        scheduleReconnect();
      };
    } catch (err) {
      setState(conn, { error: (err as Error).message, connected: false });
      conn.wsAttempts += 1;
      conn.wsDisabled = conn.wsAttempts >= 2;
      connectSse();
      scheduleReconnect();
    }
  }

  function connectTransport() {
    if (conn.cancelled) return;
    if (!conn.wsDisabled && shouldUseStreamerWs()) {
      connectWs();
      return;
    }
    connectSse();
  }

  function scheduleReconnect() {
    if (conn.cancelled) return;
    const delay = Math.min(conn.backoff, 30_000);
    setTimeout(connectTransport, delay);
    conn.backoff = Math.min(conn.backoff * 2, 30_000);
  }

  connectTransport();
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
        if (conn.ws && conn.ws.readyState !== WebSocket.CLOSED) conn.ws.close();
        if (conn.sse) conn.sse.close();
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
  const emptySubscribe = (_onStoreChange: () => void) => () => {};
  const emptySnapshot = () => initialState;
  const subscribeFn = (onStoreChange: () => void) =>
    priceStreamsDisabled ? emptySubscribe(onStoreChange) : subscribe(marketId, tokenIds, onStoreChange);
  const getSnapshot = () => (priceStreamsDisabled ? emptySnapshot() : snapshot(marketId, tokenIds));
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
