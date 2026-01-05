import { render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";
import { MarketAnalyticsPanel } from "@/components/markets/MarketAnalyticsPanel";
import type { MarketDetail } from "@/lib/api-types";

const streamMock = vi.hoisted(
  () =>
    vi.fn((..._args: unknown[]) => ({
      outcomes: [],
      trades: [],
      histories: {},
      connected: false,
      error: null,
      transport: null,
      lastUpdated: null,
    })),
);

vi.mock("@/hooks/usePriceStreamConnection", () => ({
  usePriceStreamStore: (...args: unknown[]) => streamMock(...args),
}));

describe("MarketAnalyticsPanel", () => {
  it("uses lifetime volume for avg trade size when available", () => {
    const market: MarketDetail = {
      eventId: "m-1",
      title: "Market One",
      volume: 1000,
      volume24hUsd: 200,
      tradesQuantity: 10,
    };

    render(<MarketAnalyticsPanel market={market} />);

    const label = screen.getByText("Avg trade size");
    const row = label.closest("div");
    expect(row).toHaveTextContent("$100");
  });

  it("labels avg trade size as estimate when only 24h volume is available", () => {
    const market: MarketDetail = {
      eventId: "m-2",
      title: "Market Two",
      volume24hUsd: 500,
      tradesQuantity: 10,
    };

    render(<MarketAnalyticsPanel market={market} />);

    const label = screen.getByText("Avg trade size (est.)");
    const row = label.closest("div");
    expect(row).toHaveTextContent("$50");
  });
});
