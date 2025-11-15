import { afterEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import CategoryPage from "@/app/categories/[category]/page";
import { CategoryMarkets } from "@/app/categories/[category]/CategoryMarkets";
import { fetchFeaturedMarkets } from "@/lib/api";

const featuredClientMock = vi.hoisted(() => vi.fn(() => <div data-testid="featured-client" />));

vi.mock("@/components/markets/FeaturedMarketsClient", () => ({
  FeaturedMarketsClient: featuredClientMock,
}));

vi.mock("@/lib/api", () => ({
  fetchFeaturedMarkets: vi.fn().mockResolvedValue([
    {
      eventId: "evt-category",
      title: "Category Market",
      category: "AI & Tech",
      outcomes: [],
      outcomePrices: [],
    },
  ]),
}));

vi.mock("next/navigation", async (importOriginal) => {
  const actual = await importOriginal<any>();
  return {
    ...actual,
    notFound: vi.fn(() => {
      throw new Error("NOT_FOUND");
    }),
  };
});

describe("CategoryPage", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("requests markets for the provided category", async () => {
    const ui = await CategoryMarkets({ slug: "ai-tech" });
    render(ui);
    expect(fetchFeaturedMarkets).toHaveBeenCalledWith(expect.any(Number), expect.objectContaining({ category: "ai-tech" }));
    expect(featuredClientMock).toHaveBeenCalledWith(
      expect.objectContaining({ categoryFilter: "AI & Tech", initialMarkets: expect.any(Array) }),
      expect.anything(),
    );
  });

  it("renders featured client with empty data when no markets returned", async () => {
    (fetchFeaturedMarkets as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]);
    const ui = await CategoryMarkets({ slug: "ai-tech" });
    render(ui);
    expect(featuredClientMock).toHaveBeenCalledWith(
      expect.objectContaining({ initialMarkets: [] }),
      expect.anything(),
    );
  });

  it("invokes notFound for invalid slug", async () => {
    await expect(CategoryPage({ params: Promise.resolve({ category: "unknown" }) })).rejects.toThrow("NOT_FOUND");
  });
});
