import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const originalEnv = { ...process.env };

describe("fetchMarketStatsBreakdown", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllGlobals();
    process.env = { ...originalEnv };
  });

  afterEach(() => {
    vi.resetModules();
    vi.unstubAllGlobals();
    process.env = { ...originalEnv };
  });

  it("fetches stats from the configured API base", async () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "http://localhost:8000";

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [
        { status: "live", count: 3 },
        { status: "finalized", count: 1 },
      ],
    });
    vi.stubGlobal("fetch", fetchMock);

    const { DEFAULT_API_BASE, fetchMarketStatsBreakdown } = await import("@/lib/api");
    const stats = await fetchMarketStatsBreakdown();

    expect(fetchMock).toHaveBeenCalledWith(
      `${DEFAULT_API_BASE}/markets/stats`,
      expect.objectContaining({
        next: expect.objectContaining({ revalidate: 60 }),
      }),
    );
    expect(stats).toEqual([
      { status: "live", count: 3 },
      { status: "ended", count: 1 },
      { status: "finalized", count: 1 },
      { status: "total", count: 4 },
    ]);
  });

  it("returns primary stats when data is present", async () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "http://localhost:8000";

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [
        { status: "live", count: 2 },
        { status: "finalized", count: 5 },
      ],
    });
    vi.stubGlobal("fetch", fetchMock);

    const { fetchMarketStatsBreakdown } = await import("@/lib/api");
    const stats = await fetchMarketStatsBreakdown();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(stats).toEqual([
      { status: "live", count: 2 },
      { status: "ended", count: 5 },
      { status: "finalized", count: 5 },
      { status: "total", count: 7 },
    ]);
  });

  it("does not fallback when no secondary API is configured", async () => {
    process.env.RM_ENVIRONMENT = "local";
    process.env.NEXT_PUBLIC_API_BASE_URL = "http://localhost:8000";

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [],
    });
    vi.stubGlobal("fetch", fetchMock);

    const { fetchMarketStatsBreakdown } = await import("@/lib/api");
    const stats = await fetchMarketStatsBreakdown();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(stats).toEqual([
      { status: "live", count: 0 },
      { status: "ended", count: 0 },
      { status: "finalized", count: 0 },
      { status: "total", count: 0 },
    ]);
  });

  it("does not fallback when RM_ENVIRONMENT is prod", async () => {
    process.env.RM_ENVIRONMENT = "prod";
    process.env.NEXT_PUBLIC_API_BASE_URL = "https://api.revealmarket.xyz";

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [{ status: "live", count: 9 }],
    });
    vi.stubGlobal("fetch", fetchMock);

    const { fetchMarketStatsBreakdown } = await import("@/lib/api");
    const stats = await fetchMarketStatsBreakdown();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(stats).toEqual([
      { status: "live", count: 9 },
      { status: "ended", count: 0 },
      { status: "finalized", count: 0 },
      { status: "total", count: 9 },
    ]);
  });
});
