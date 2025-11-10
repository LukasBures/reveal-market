import { describe, expect, it, vi } from "vitest";
import TagPage, { TagMarkets } from "@/app/tags/[tag]/page";
import { fetchFeaturedMarkets } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  fetchFeaturedMarkets: vi.fn().mockResolvedValue([
    {
      eventId: "evt-tag",
      title: "Tagged Market",
      category: "Politics",
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

describe("TagPage", () => {
  it("requests markets for the provided tag", async () => {
    await TagMarkets({ slug: "btc-halving" });
    expect(fetchFeaturedMarkets).toHaveBeenCalledWith(
      expect.any(Number),
      expect.objectContaining({ tag: "btc-halving" }),
    );
  });

  it("invokes notFound for invalid slug", async () => {
    await expect(TagPage({ params: Promise.resolve({ tag: "unknown" }) })).rejects.toThrow("NOT_FOUND");
  });
});
