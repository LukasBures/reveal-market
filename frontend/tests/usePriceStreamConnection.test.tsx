import { renderHook, act } from "@testing-library/react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { usePriceStreamStore } from "@/hooks/usePriceStreamConnection";

class FakeWebSocket {
  static CLOSED = 3;
  onopen?: () => void;
  onmessage?: (event: { data: string }) => void;
  onerror?: (event: Event) => void;
  onclose?: (event: Event) => void;
  readyState = 0;
  closeCalled = false;

  triggerOpen() {
    this.readyState = 1;
    this.onopen?.();
  }

  triggerMessage(data: string) {
    this.onmessage?.({ data });
  }

  triggerError() {
    this.onerror?.(new Event("error"));
    this.close();
  }

  triggerClose() {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.(new Event("close"));
  }

  close() {
    this.readyState = FakeWebSocket.CLOSED;
    this.closeCalled = true;
    this.onclose?.(new Event("close"));
  }
}

class FakeEventSource {
  onopen?: () => void;
  onmessage?: (event: { data: string }) => void;
  onerror?: (event: Event) => void;
  closed = false;

  triggerOpen() {
    this.onopen?.();
  }

  triggerMessage(data: string) {
    this.onmessage?.({ data });
  }

  triggerError() {
    this.onerror?.(new Event("error"));
  }

  close() {
    this.closed = true;
  }
}

const wsInstances: FakeWebSocket[] = [];
const esInstances: FakeEventSource[] = [];

vi.mock("@/lib/pricing-client", () => ({
  shouldUseStreamerWs: () => true,
  priceStreamsDisabled: false,
  createMarketWebSocket: vi.fn(() => {
    const ws = new FakeWebSocket();
    wsInstances.push(ws);
    return ws as unknown as WebSocket;
  }),
  createMarketStream: vi.fn(() => {
    const es = new FakeEventSource();
    esInstances.push(es);
    return es as unknown as EventSource;
  }),
}));

describe("usePriceStreamConnection fallbacks", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
    wsInstances.length = 0;
    esInstances.length = 0;
  });

  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("falls back to SSE after websocket failure and retries upgrade", async () => {
    const { result } = renderHook(() => usePriceStreamStore("m-fallback", ["yes", "no"]));
    expect(wsInstances.length).toBe(1);
    const ws = wsInstances[0];

    await act(async () => {
      ws.triggerError();
    });
    expect(esInstances.length).toBeGreaterThanOrEqual(1);
    const es = esInstances[esInstances.length - 1];

    await act(async () => {
      es.triggerOpen();
    });
    expect(result.current.connected).toBe(true);

    await act(async () => {
      vi.advanceTimersByTime(16_000);
    });
    expect(wsInstances.length).toBeGreaterThanOrEqual(2);
  });
});
