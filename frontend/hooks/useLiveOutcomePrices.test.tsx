import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import { useLiveOutcomePrices } from "./useLiveOutcomePrices";

class EventSourceMock {
  static instances: EventSourceMock[] = [];
  onmessage: ((ev: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  url: string;
  readyState = 1;

  constructor(url: string) {
    this.url = url;
    EventSourceMock.instances.push(this);
  }

  close() {
    this.readyState = 2;
  }
}

describe("useLiveOutcomePrices", () => {
  const originalEventSource = global.EventSource;

  beforeEach(() => {
    // @ts-expect-error override
    global.EventSource = EventSourceMock;
    EventSourceMock.instances = [];
  });

  afterEach(() => {
    // @ts-expect-error restore
    global.EventSource = originalEventSource;
  });

  it("overrides SSR prices with live display_price", () => {
    const { result } = renderHook(() => useLiveOutcomePrices("m1", [0.1, 0.2]));
    expect(result.current.prices[0]).toBeCloseTo(0.1);
    const es = EventSourceMock.instances[0];
    act(() => {
      es.onmessage?.({ data: JSON.stringify({ outcome: 0, price: "0.4", display_price: "0.45" }) });
    });
    expect(result.current.prices[0]).toBeCloseTo(0.45);
  });

  it("tracks fx stale flag", () => {
    const { result } = renderHook(() => useLiveOutcomePrices("m1", [0.1]));
    const es = EventSourceMock.instances[0];
    act(() => {
      es.onmessage?.({ data: JSON.stringify({ outcome: 0, price: "0.2", display_price: "0.22", fx_stale: true }) });
    });
    expect(result.current.outcomes[0]?.fxStale).toBe(true);
  });
});
