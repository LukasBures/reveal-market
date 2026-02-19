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

  triggerError() {
    this.onerror?.(new Event("error"));
    this.close();
  }

  close() {
    this.readyState = FakeWebSocket.CLOSED;
    this.closeCalled = true;
    this.onclose?.(new Event("close"));
  }
}

const wsInstances: FakeWebSocket[] = [];

vi.mock("@/lib/pricing-client", () => ({
  shouldUseStreamerWs: () => true,
  priceStreamsDisabled: false,
  createMarketWebSocket: vi.fn(() => {
    const ws = new FakeWebSocket();
    wsInstances.push(ws);
    return ws as unknown as WebSocket;
  }),
}));

describe("usePriceStreamConnection fallbacks", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
    wsInstances.length = 0;
  });

  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("retries websocket after failure without SSE fallback", async () => {
    const { result } = renderHook(() => usePriceStreamStore("m-fallback", ["yes", "no"]));
    expect(wsInstances.length).toBe(1);
    const ws = wsInstances[0];

    await act(async () => {
      ws.triggerError();
    });
    expect(result.current.connected).toBe(false);
    await act(async () => {
      vi.advanceTimersByTime(2000);
    });
    expect(wsInstances.length).toBeGreaterThanOrEqual(2);
  });
});
