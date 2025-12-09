import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MarketCard } from "@/components/markets/MarketCard";

vi.mock("next/image", () => ({
  default: ({ alt, src }: { alt?: string; src?: string }) => (
    <img alt={alt} src={typeof src === "string" ? src : undefined} data-testid="market-image" />
  ),
}));
vi.mock("next/link", () => ({
  __esModule: true,
  default: ({ href, children, prefetch: _prefetch, ...rest }: any) => {
    let resolved = "#";
    if (typeof href === "string") {
      resolved = href;
    } else if (href?.pathname) {
      resolved = href.pathname;
      const params = href.params || href.query || {};
      Object.keys(params).forEach((key) => {
        resolved = resolved.replace(`[${key}]`, params[key]);
      });
    }
    return (
      <a href={resolved} {...rest}>
        {children}
      </a>
    );
  },
}));

const baseMarket = {
  eventId: "evt-card",
  title: "Card Coverage",
  category: "Crypto",
  status: "commit",
  commitDeadline: "2025-01-01T00:00:00.000Z",
  liquidityUsd: 125000,
  volume24hUsd: 100000,
  outcomes: ["Yes", "No", "Maybe"],
  outcomePrices: [0.72, 0.2, 0.08],
  tags: ["BTC"],
};

describe("MarketCard", () => {
  it("renders headline stats, CTA link, and outcome probabilities", () => {
    render(<MarketCard market={{ ...baseMarket, imageUrl: "https://cdn.example/cover.jpg" }} />);

    expect(screen.getByRole("link", { name: /card coverage/i })).toHaveAttribute("href", "/markets/evt-card");
    expect(screen.getAllByTestId("market-image")[0]).toHaveAttribute("src", "https://cdn.example/cover.jpg");
    expect(screen.getByText("72%")).toBeInTheDocument();
    expect(screen.getByText("20%")).toBeInTheDocument();
  });

  it("falls back to placeholder when no image exists", () => {
    render(<MarketCard market={{ ...baseMarket, imageUrl: undefined }} />);
    const img = screen.getAllByTestId("market-image")[0];
    expect(img.getAttribute("src")).toMatch(/^data:image\/svg\+xml/);
  });

  it("uses extraData image_url when provided", () => {
    render(
      <MarketCard
        market={{
          ...baseMarket,
          imageUrl: undefined,
          extraData: { image_url: "https://cdn.example/extra.jpg" },
        }}
      />,
    );
    expect(screen.getAllByTestId("market-image")[0]).toHaveAttribute("src", "https://cdn.example/extra.jpg");
  });

  it("falls back to gamma image metadata", () => {
    render(
      <MarketCard
        market={{
          ...baseMarket,
          imageUrl: undefined,
          extraData: { gamma: { image_url: "https://cdn.gamma/example.png" } },
        }}
      />,
    );
    expect(screen.getAllByTestId("market-image")[0]).toHaveAttribute("src", "https://cdn.gamma/example.png");
  });

  it("derives missing binary probability from the complement", () => {
    render(
      <MarketCard
        market={{
          ...baseMarket,
          outcomes: ["Yes", "No"],
          outcomePrices: [0.6],
        }}
      />,
    );
    expect(screen.getByText("60%")).toBeInTheDocument();
    expect(screen.getByText("40%")).toBeInTheDocument();
  });

  it("shows binary stats for volume and liquidity", () => {
    render(
      <MarketCard
        market={{
          ...baseMarket,
          outcomes: ["Yes", "No"],
          outcomePrices: [0.55, 0.45],
          liquidityUsd: 250000,
          volume24hUsd: 100000,
        }}
      />,
    );
    expect(screen.getByText(/24h vol/i)).toBeInTheDocument();
    expect(screen.getByText("$100K")).toBeInTheDocument();
    expect(screen.getByText(/Liquidity/i)).toBeInTheDocument();
    expect(screen.getByText("$250K")).toBeInTheDocument();
  });
});
