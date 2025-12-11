import { render, screen } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MarketFomoOverlay } from "@/components/markets/MarketFomoOverlay";

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

describe("MarketFomoOverlay", () => {
  beforeEach(() => {
    mocks.usePriceStreamStore.mockReset();
    mocks.useFxStream.mockReset();
    mocks.useFxStream.mockReturnValue({ fx: { zen_usd: 1 }, status: "live" });
  });

  it("returns null when there are no valid trades to display", () => {
    mocks.usePriceStreamStore.mockReturnValue({ trades: [] });

    const { container } = render(<MarketFomoOverlay marketId="m1" />);

    expect(container.firstChild).toBeNull();
  });

  it("renders recent trades with USD labels", () => {
    mocks.usePriceStreamStore.mockReturnValue({
      trades: [
        { price: 2, size: 5, side: "BUY", timestamp: "2023-01-01T00:00:00Z" },
        { price: 1.5, size: 3, side: "SELL", timestamp: "2023-01-01T00:01:00Z" },
      ],
    });
    mocks.useFxStream.mockReturnValue({ fx: { zen_usd: 2 }, status: "stale" });

    render(<MarketFomoOverlay marketId="m2" tokenIds={["a", "b"]} />);

    expect(screen.getByText("$20.00")).toBeInTheDocument();
    expect(screen.getByText("$9.00")).toBeInTheDocument();
    expect(screen.getAllByText(/fx stale/i)).toHaveLength(2);
    expect(screen.getByText(/buy/i)).toBeInTheDocument();
    expect(screen.getByText(/sell/i)).toBeInTheDocument();
  });
});
