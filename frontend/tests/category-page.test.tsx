import { afterEach, describe, expect, it, vi } from "vitest";
import CategoryPage from "@/app/categories/[category]/page";
import { CategoryMarkets } from "@/app/categories/[category]/CategoryMarkets";
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
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("requests markets for the provided category", async () => {
    await CategoryMarkets({ slug: "ai-tech" });
    expect(fetchFeaturedMarkets).toHaveBeenCalledWith(
      expect.any(Number),
      expect.objectContaining({ category: "ai-tech" }),
    );
  });

  it("falls back to featured markets when the category feed is empty", async () => {
    const mock = fetchFeaturedMarkets as unknown as ReturnType<typeof vi.fn>;
    mock.mockResolvedValueOnce([]);
    mock.mockResolvedValueOnce([
      {
        eventId: "evt-category",
        title: "Category Market",
        category: "AI & Tech",
        outcomes: [],
        outcomePrices: [],
      },
    ]);

    await CategoryMarkets({ slug: "ai-tech" });

    expect(mock).toHaveBeenCalledTimes(2);
    expect(mock.mock.calls[0]?.[1]).toMatchObject({ category: "ai-tech" });
    expect(mock.mock.calls[1]?.length).toBe(1);
  });

  it("invokes notFound for invalid slug", async () => {
    await expect(CategoryPage({ params: Promise.resolve({ category: "unknown" }) })).rejects.toThrow("NOT_FOUND");
  });
});
