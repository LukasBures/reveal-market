import { describe, expect, it, vi } from "vitest";
import CategoryPage, { CategoryMarkets } from "@/app/categories/[category]/page";
import { fetchFeaturedMarkets } from "@/lib/api";

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
  it("requests markets for the provided category", async () => {
    await CategoryMarkets({ slug: "ai-tech" });
    expect(fetchFeaturedMarkets).toHaveBeenCalledWith(
      expect.any(Number),
      expect.objectContaining({ category: "ai-tech" }),
    );
  });

  it("invokes notFound for invalid slug", async () => {
    await expect(CategoryPage({ params: Promise.resolve({ category: "unknown" }) })).rejects.toThrow("NOT_FOUND");
  });
});
