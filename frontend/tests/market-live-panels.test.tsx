import { render, screen } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MarketLivePanels } from "@/components/markets/MarketLivePanels";

const usePriceStreamStoreMock = vi.hoisted(() => vi.fn());

vi.mock("@/hooks/usePriceStreamConnection", () => ({
  usePriceStreamStore: usePriceStreamStoreMock,
}));

describe("MarketLivePanels", () => {
  beforeEach(() => {
    usePriceStreamStoreMock.mockReset();
  });

  it("shows live pricing depth, spread, and trades", () => {
    usePriceStreamStoreMock.mockReturnValue({
      connected: true,
      error: null,
      outcomes: [
        {
          bestBid: 0.34,
          bestAsk: 0.36,
          depthBids: [{ price: 0.34, size: 10 }],
          depthAsks: [{ price: 0.36, size: 20 }],
        },
      ],
      histories: {},
      trades: [{ price: 0.35, size: 50, side: "BUY", timestamp: "2023-01-01T00:00:00Z" }],
      tickSize: 0.01,
      status: "live",
      transport: "ws",
      lastUpdated: "2023-01-01T00:00:00Z",
      fxStale: false,
    });

    render(<MarketLivePanels marketId="m-live" />);

    expect(screen.getByText(/live \(ws\)/i)).toBeInTheDocument();
    expect(screen.getByText(/transport ws/i)).toBeInTheDocument();
    expect(screen.getByText(/fx live/i)).toBeInTheDocument();
    expect(screen.getAllByText("0.340").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("0.360").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("5.56%")).toBeInTheDocument();
    expect(screen.getAllByText(/00:00:00/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/buy/i)).toBeInTheDocument();
    expect(screen.getByText("0.350")).toBeInTheDocument();
    expect(screen.getByText("50.00")).toBeInTheDocument();
  });

  it("surfaces stream errors and placeholder trade content", () => {
    usePriceStreamStoreMock.mockReturnValue({
      connected: false,
      error: "socket failed",
      outcomes: [{}],
      histories: {},
      trades: [],
      tickSize: undefined,
      status: null,
      transport: null,
      lastUpdated: null,
      fxStale: true,
    });

    render(<MarketLivePanels marketId="m-error" tokenIds={["x"]} />);

    expect(screen.getAllByText(/stream error/i)).toHaveLength(2);
    expect(screen.getByText(/transport n\/a/i)).toBeInTheDocument();
    expect(screen.getByText(/fx stale/i)).toBeInTheDocument();
    expect(screen.getByText(/no trades yet/i)).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });
});
