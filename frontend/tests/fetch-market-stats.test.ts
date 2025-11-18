import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchMarketStatsBreakdown } from "@/lib/api";

describe("fetchMarketStatsBreakdown", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("normalizes live/finalized counts and derives totals", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [
        { status: "live", count: 4 },
        { status: "finalized", count: 3 },
      ],
    });
    vi.stubGlobal("fetch", fetchMock);

    const stats = await fetchMarketStatsBreakdown();
    expect(stats).toEqual([
      { status: "live", count: 4 },
      { status: "finalized", count: 3 },
      { status: "total", count: 7 },
    ]);
  });

  it("handles unexpected payloads gracefully", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: "live", count: 5 }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const stats = await fetchMarketStatsBreakdown();
    expect(stats).toEqual([]);
  });
});
