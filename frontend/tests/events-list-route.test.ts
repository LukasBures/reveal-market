import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  fetchFeaturedEvents: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  fetchFeaturedEvents: mocks.fetchFeaturedEvents,
}));

describe("/api/events/list route", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
  });

  it("forwards pagination and list filters to the events fetcher", async () => {
    mocks.fetchFeaturedEvents.mockResolvedValue({ data: [{ eventId: "evt-1", title: "Event", markets: [] }] });
    const { GET } = await import("@/app/api/events/list/route");

    const response = await GET(
      new Request(
        "https://reveal.test/api/events/list?limit=30&offset=30&status=active&order_by=volume&closes_within_hours=24",
      ),
    );

    expect(response.status).toBe(200);
    expect(mocks.fetchFeaturedEvents).toHaveBeenCalledWith(
      30,
      expect.objectContaining({
        offset: 30,
        status: "active",
        orderBy: "volume",
        closesWithinHours: 24,
      }),
    );
    await expect(response.json()).resolves.toEqual([{ eventId: "evt-1", title: "Event", markets: [] }]);
  });

  it("returns an error status when the upstream events fetch fails", async () => {
    mocks.fetchFeaturedEvents.mockResolvedValue({ data: [], error: "timeout" });
    const { GET } = await import("@/app/api/events/list/route");

    const response = await GET(new Request("https://reveal.test/api/events/list?limit=30"));

    expect(response.status).toBe(502);
    await expect(response.json()).resolves.toEqual({ error: "timeout" });
  });
});
