import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MarketGrid } from "@/components/markets/MarketGrid";

const sampleMarkets = [
  {
    eventId: "evt-a",
    title: "A Market",
    category: "Politics",
  },
  {
    eventId: "evt-b",
    title: "B Market",
    category: "Sports",
  },
];

describe("MarketGrid", () => {
  it("returns an empty state when no markets provided", () => {
    render(<MarketGrid markets={[]} />);
    expect(screen.getByText(/markets will appear here once/i)).toBeInTheDocument();
  });

  it("renders one card per market", () => {
    render(<MarketGrid markets={sampleMarkets} />);
    expect(screen.getAllByRole("link")).toHaveLength(2);
  });
});
