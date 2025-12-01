import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MarketDetailSidebar } from "@/components/markets/MarketDetailSidebar";
import { formatDateTime } from "@/lib/formatters";
import type { MarketDetail } from "@/lib/api-types";

const detailMarket: MarketDetail = {
  eventId: "evt-side",
  title: "Sidebar Market",
  category: "Crypto",
  status: "commit",
  createdAt: "2025-01-01T00:00:00.000Z",
  commitDeadline: "2025-02-01T00:00:00.000Z",
  revealDeadline: "2025-03-01T00:00:00.000Z",
  tags: ["BTC"],
  liquidityUsd: 50000,
  rakeBps: 25,
  extraData: {
    gamma: {
      clobPairId: "pair-123",
      clobTokenIds: ["token-a", "token-b"],
      makerFeeBps: 5,
      takerFeeBps: 15,
      volume24h: 10000,
    },
  },
  resolution: {
    resolved: false,
    winners: [],
    checkedAt: "2025-01-10T00:00:00.000Z",
  },
};

describe("MarketDetailSidebar", () => {
  it("displays category, status, and fee schedule", () => {
    render(<MarketDetailSidebar market={detailMarket} />);

    expect(screen.getByText("Crypto")).toBeInTheDocument();
    expect(screen.getAllByText(/commit/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/fee schedule/i)).toBeInTheDocument();
    expect(screen.getByText("25 bps")).toBeInTheDocument();
    expect(screen.getByText(/maker fee/i)).toBeInTheDocument();
  });

  it("shows order book routing details when provided", () => {
    render(<MarketDetailSidebar market={detailMarket} />);
    expect(screen.getByText(/pair id/i)).toBeInTheDocument();
    expect(screen.getByText(/pair-123/i)).toBeInTheDocument();
    expect(screen.getByText(/token ids/i)).toBeInTheDocument();
    expect(screen.getByText(/token-a, token-b/i)).toBeInTheDocument();
  });

  it("falls back to TBA when deadlines are missing", () => {
    render(
      <MarketDetailSidebar
        market={{
          ...detailMarket,
          commitDeadline: undefined,
          revealDeadline: undefined,
        }}
      />,
    );
    const createdAtFormatted = formatDateTime(detailMarket.createdAt);
    expect(screen.getByText(createdAtFormatted)).toBeInTheDocument();
    expect(screen.getAllByText(/tba/i)).toHaveLength(1);
  });
});
