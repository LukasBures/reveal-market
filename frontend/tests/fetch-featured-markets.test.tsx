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
      expect.stringContaining("/events?limit=6&status=active&order_by=volume&coalesce_groups=1"),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    // closes_within_hours should not be present when closesWithinHours is not explicitly provided
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).not.toContain("closes_within_hours");
  });

  it("adds category filter as query param when provided", async () => {
    await fetchFeaturedEvents(10, { category: "Sports" });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining(
        "/events?limit=10&status=active&order_by=volume&coalesce_groups=1&category=sports",
      ),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("returns an empty list when the network request fails", async () => {
    fetchMock.mockRejectedValueOnce(new Error("offline"));
    const result = await fetchFeaturedEvents(4);
    expect(result).toEqual({ data: [], error: "offline" });
  });
});
