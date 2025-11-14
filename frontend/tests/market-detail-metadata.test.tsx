import { render, screen } from "@testing-library/react";
import React from "react";
import { MarketDetailMetadata } from "@/components/markets/MarketDetailMetadata";
import type { MarketDetail } from "@/lib/api-types";

const baseMarket: MarketDetail = {
  eventId: "evt-1",
  title: "Will the Fed cut rates?",
  category: "macro",
  tags: ["fed", "macro"],
  status: "commit",
  commitDeadline: "2025-12-01T00:00:00.000Z",
  revealDeadline: "2025-12-05T00:00:00.000Z",
  outcomes: ["Yes", "No"],
  outcomePrices: [0.45, 0.55],
  imageUrl: null,
  slug: "fed-cut-rates",
  conditionId: "0xabc",
  questionId: "0xdef",
  umaStatus: "resolved",
  oracle: "UMA",
  marketAddress: "0x123",
  createdAt: "2025-11-01T00:00:00.000Z",
  updatedAt: "2025-11-02T00:00:00.000Z",
  extraData: { description: "Mirror" },
};

describe("MarketDetailMetadata", () => {
  it("renders core identifiers and tags", () => {
    render(<MarketDetailMetadata market={baseMarket} />);

    expect(screen.getByText("Identifiers & provenance")).toBeInTheDocument();
    expect(screen.getByText(baseMarket.conditionId!)).toBeInTheDocument();
    expect(screen.getByText("#fed")).toBeInTheDocument();
    expect(screen.getByText("#macro")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /copy condition id/i })).toBeInTheDocument();
  });

  it("hides tags when metadata missing", () => {
    const market: MarketDetail = {
      ...baseMarket,
      tags: [],
      slug: undefined,
      conditionId: undefined,
      questionId: undefined,
    };

    render(<MarketDetailMetadata market={market} />);

    expect(screen.queryByText("#fed")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /copy condition id/i })).not.toBeInTheDocument();
  });
});
