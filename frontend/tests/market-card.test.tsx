import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MarketCard } from "@/components/markets/MarketCard";

vi.mock("next/image", () => ({
  default: ({ alt }: { alt?: string }) => <img alt={alt} />,
}));

const baseMarket = {
  eventId: "evt-card",
  title: "Card Coverage",
  category: "Crypto",
  status: "commit",
  commitDeadline: "2025-01-01T00:00:00.000Z",
  liquidityUsd: 125000,
  outcomes: ["Yes", "No", "Maybe"],
  outcomePrices: [0.72, 0.2, 0.08],
  tags: ["BTC"],
};

describe("MarketCard", () => {
  it("renders headline stats and CTA link", () => {
    render(<MarketCard market={{ ...baseMarket, imageUrl: "https://cdn.example/cover.jpg" }} />);

    expect(screen.getByRole("link", { name: /card coverage/i })).toHaveAttribute("href", "/markets/evt-card");
    expect(screen.getByRole("img", { name: /artwork for card coverage/i })).toBeInTheDocument();
    expect(screen.getAllByText("72%").length).toBeGreaterThan(0);
    expect(screen.getByText("$125,000")).toBeInTheDocument();
  });

  it("falls back gracefully when no image exists", () => {
    render(<MarketCard market={{ ...baseMarket, imageUrl: undefined }} />);
    expect(screen.getByRole("link", { name: /card coverage/i })).toBeInTheDocument();
    expect(screen.getByText("Yes")).toBeInTheDocument();
    expect(screen.getByText("No")).toBeInTheDocument();
  });
});
