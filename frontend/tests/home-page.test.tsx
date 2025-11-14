import { render, screen } from "@testing-library/react";
import { vi } from "vitest";
import HomePage from "@/app/page";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    fetchFeaturedMarkets: vi.fn().mockResolvedValue([
      {
        eventId: "evt-1",
        title: "Sample market",
        category: "Politics",
        outcomes: ["Yes", "No"],
        outcomePrices: [0.7, 0.3],
      },
    ]),
  };
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    prefetch: vi.fn(),
  }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/components/markets/MarketFilters", () => ({
  MarketFilters: () => <div data-testid="filters">Filters</div>,
}));

vi.mock("@/components/markets/FeaturedMarketsSection", () => ({
  FeaturedMarketsSection: () => <div data-testid="featured">Featured Markets</div>,
  FeaturedMarketsSkeleton: () => <div data-testid="featured-skeleton">Loading…</div>,
}));

describe("HomePage", () => {
  it("renders filters and market cards", async () => {
    const ui = await HomePage({ searchParams: Promise.resolve({}) });
    render(ui);

    expect(screen.getByTestId("filters")).toBeInTheDocument();
    expect(screen.getByTestId("featured")).toBeInTheDocument();
  });
});
