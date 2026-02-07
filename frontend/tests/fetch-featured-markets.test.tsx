import { describe, beforeEach, afterEach, it, expect, vi } from "vitest";
import { fetchFeaturedEvents } from "@/lib/api";

describe("fetchFeaturedEvents", () => {
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

  it("calls /events by default", async () => {
    await fetchFeaturedEvents(6);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/events?limit=6&status=active&order_by=volume&closes_within_hours=24&coalesce_groups=1"),
      expect.objectContaining({
        next: expect.objectContaining({ tags: ["markets:list"] }),
      }),
    );
  });

  it("adds category filter as query param when provided", async () => {
    await fetchFeaturedEvents(10, { category: "Sports" });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining(
        "/events?limit=10&status=active&order_by=volume&closes_within_hours=24&coalesce_groups=1&category=sports",
      ),
      expect.objectContaining({
        next: expect.objectContaining({ tags: ["category:sports"] }),
      }),
    );
  });

  it("returns an empty list when the network request fails", async () => {
    fetchMock.mockRejectedValueOnce(new Error("offline"));
    const result = await fetchFeaturedEvents(4);
    expect(result).toEqual([]);
  });
});
