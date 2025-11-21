import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MarketDetailHeader } from "@/components/markets/MarketDetailHeader";
import type { MarketDetail } from "@/lib/api-types";

const baseMarket: MarketDetail = {
  eventId: "evt-zen",
  title: "Market Detail Header",
  category: "Sports",
  outcomes: ["Yes", "No"],
  outcomePrices: [0.7, 0.3],
  status: "commit",
  commitDeadline: "2025-01-01T00:00:00.000Z",
  revealDeadline: "2025-01-02T00:00:00.000Z",
};

describe("MarketDetailHeader", () => {
  it("renders buy buttons for outcome 0/1", () => {
    render(<MarketDetailHeader market={baseMarket} />);

    expect(screen.getByRole("link", { name: /buy yes/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /buy no/i })).toBeInTheDocument();
    expect(screen.getByText(/70%/)).toBeInTheDocument();
    expect(screen.getByText(/30%/)).toBeInTheDocument();
  });
});
