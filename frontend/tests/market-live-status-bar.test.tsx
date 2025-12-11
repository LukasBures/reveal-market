import { render, screen } from "@testing-library/react";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MarketLiveStatusBar } from "@/components/markets/MarketLiveStatusBar";

const mocks = vi.hoisted(() => ({
  usePriceStreamStore: vi.fn(),
  useFxStream: vi.fn(),
}));

vi.mock("@/hooks/usePriceStreamConnection", () => ({
  usePriceStreamStore: mocks.usePriceStreamStore,
}));

vi.mock("@/hooks/useFxStream", () => ({
  useFxStream: mocks.useFxStream,
}));

describe("MarketLiveStatusBar", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2023-01-01T00:00:10Z"));
    mocks.usePriceStreamStore.mockReset();
    mocks.useFxStream.mockReset();
  });

  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
  });

  it("shows live connection, FX status, and tick metadata", () => {
    mocks.usePriceStreamStore.mockReturnValue({
      connected: true,
      error: null,
      transport: "ws",
      trades: [
        { timestamp: "2023-01-01T00:00:05Z" },
        { timestamp: "2023-01-01T00:00:08Z" },
      ],
      histories: { 0: [{}, {}], 1: [{}] },
      outcomes: [],
      tickSize: 0.01,
      lastUpdated: "2023-01-01T00:00:09Z",
    });
    mocks.useFxStream.mockReturnValue({
      fx: { zen_usd: 1.5 },
      status: "live",
      lastUpdate: new Date("2023-01-01T00:00:05Z").getTime(),
      wsConnected: true,
      restFallbacks: 1,
    });

    render(<MarketLiveStatusBar marketId="m-live" />);

    expect(screen.getByText(/live \(ws\)/i)).toBeInTheDocument();
    expect(screen.getByText(/ws live @ 1\.5000 5s/i)).toBeInTheDocument();
    expect(screen.getByText(/fx rest 1/i)).toBeInTheDocument();
    expect(screen.getByText(/trades 2 \/ hist 3/i)).toBeInTheDocument();
    expect(screen.getByText(/last trade 00:00:08/i)).toBeInTheDocument();
    expect(screen.getByText(/last tick 00:00:09 \(1s\)/i)).toBeInTheDocument();
    expect(screen.getByText(/tick size 0\.01/i)).toBeInTheDocument();
  });

  it("surfaces stream errors and reconnection state", () => {
    mocks.usePriceStreamStore.mockReturnValue({
      connected: false,
      error: "socket failure",
      transport: null,
      trades: [],
      histories: {},
      outcomes: [],
      tickSize: undefined,
      lastUpdated: null,
    });
    mocks.useFxStream.mockReturnValue({
      fx: null,
      status: "error",
      lastUpdate: 0,
      wsConnected: false,
      restFallbacks: 0,
    });

    render(<MarketLiveStatusBar marketId="m-error" tokenIds={["x"]} />);

    expect(screen.getByText(/stream error/i)).toBeInTheDocument();
    expect(screen.getByText(/rest error/i)).toBeInTheDocument();
    expect(screen.getByText(/fx rest 0/i)).toBeInTheDocument();
  });
});
