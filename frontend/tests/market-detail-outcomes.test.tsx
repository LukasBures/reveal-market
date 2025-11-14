import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MarketDetailOutcomes } from "@/components/markets/MarketDetailOutcomes";
import type { MarketDetail } from "@/lib/api";

const baseDetail: MarketDetail = {
  eventId: "evt-detail",
  title: "Detail",
  category: "General",
  outcomes: ["Yes", "No"],
  outcomePrices: [0.6, 0.4],
};

describe("MarketDetailOutcomes", () => {
  it("renders an informative empty state when no outcomes exist", () => {
    render(<MarketDetailOutcomes market={{ ...baseDetail, outcomes: [] }} />);
    expect(screen.getByText(/no outcome data available/i)).toBeInTheDocument();
  });

  it("shows each outcome with its probability", () => {
    render(<MarketDetailOutcomes market={baseDetail} />);
    expect(screen.getByText("Yes")).toBeInTheDocument();
    expect(screen.getByText("60%")).toBeInTheDocument();
    expect(screen.getByText("No")).toBeInTheDocument();
    expect(screen.getByText("40%")).toBeInTheDocument();
  });
});
