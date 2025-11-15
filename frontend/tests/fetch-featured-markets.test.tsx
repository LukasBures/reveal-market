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

  it("returns an empty list when the network request fails", async () => {
    fetchMock.mockRejectedValueOnce(new Error("offline"));
    const result = await fetchFeaturedMarkets(4);
    expect(result).toEqual([]);
  });
});
