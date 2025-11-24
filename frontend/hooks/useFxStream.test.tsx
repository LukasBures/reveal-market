import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import { useFxStream } from "./useFxStream";

class WebSocketMock {
  static instances: WebSocketMock[] = [];
  static OPEN = 1;
  url: string;
  readyState = WebSocketMock.OPEN;
  onopen: ((ev?: any) => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: ((ev?: any) => void) | null = null;
  onerror: ((ev?: any) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    WebSocketMock.instances.push(this);
  }

  send() {}

  close() {
    this.readyState = 3;
    this.onclose?.({});
  }
}

describe("useFxStream", () => {
  const originalWebSocket = global.WebSocket;
  const originalFetch = global.fetch;

  beforeEach(() => {
    WebSocketMock.instances = [];
    // @ts-expect-error override for tests
    global.WebSocket = WebSocketMock;
    global.fetch = vi.fn();
    vi.useFakeTimers();
  });

  afterEach(() => {
    // @ts-expect-error restore
    global.WebSocket = originalWebSocket;
    global.fetch = originalFetch;
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.resetAllMocks();
  });

  it("hydrates from websocket and marks stale", () => {
    const { result } = renderHook(() => useFxStream("/fx/zen-usdc"));
    expect(WebSocketMock.instances).toHaveLength(1);
    const socket = WebSocketMock.instances[0];

    act(() => {
      socket.onmessage?.({ data: JSON.stringify({ zen_usd: 12.5, raw_zen_usd: 13, stale: false }) });
    });
    expect(result.current.fx?.zen_usd).toBeCloseTo(12.5);
    expect(result.current.status).toBe("live");

    act(() => {
      socket.onmessage?.({ data: JSON.stringify({ zen_usd: 12.5, raw_zen_usd: 13, stale: true }) });
    });
    expect(result.current.status).toBe("stale");
  });

  it("reconnects on close with backoff", () => {
    renderHook(() => useFxStream("/fx/zen-usdc"));
    expect(WebSocketMock.instances).toHaveLength(1);
    act(() => {
      WebSocketMock.instances[0].onclose?.({});
    });
    act(() => {
      vi.advanceTimersByTime(1100);
    });
    expect(WebSocketMock.instances.length).toBeGreaterThan(1);
  });

  it("falls back to HTTP when socket silent", async () => {
    (global.fetch as unknown as vi.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({ zen_usd: 9.1, raw_zen_usd: 9.4, stale: false }),
    });
    const { result } = renderHook(() => useFxStream("/fx/zen-usdc"));
    await act(async () => {
      vi.advanceTimersByTime(6000);
    });
    expect(result.current.fx?.zen_usd).toBeCloseTo(9.1);
    expect(global.fetch).toHaveBeenCalled();
  });
});
