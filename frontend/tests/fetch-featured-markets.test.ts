import { describe, beforeEach, afterEach, it, expect, vi } from "vitest";
import { fetchFeaturedMarkets } from "@/lib/api";

describe("fetchFeaturedMarkets", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [],
    });
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("calls /markets by default", async () => {
    await fetchFeaturedMarkets(6);
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/markets?limit=6"), expect.objectContaining({
      next: expect.objectContaining({ tags: ["markets:list"] }),
    }));
  });

  it("targets the categories endpoint when category filter provided", async () => {
    await fetchFeaturedMarkets(10, { category: "Sports" });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/categories/sports?limit=10"),
      expect.objectContaining({
        next: expect.objectContaining({ tags: ["category:sports"] }),
      }),
    );
  });

  it("targets the tags endpoint when tag filter provided", async () => {
    await fetchFeaturedMarkets(8, { tag: "btc halving" });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/tags/btc-halving?limit=8"),
      expect.objectContaining({
        next: expect.objectContaining({ tags: ["tag:btc-halving"] }),
      }),
    );
  });
});
