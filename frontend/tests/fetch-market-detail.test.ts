import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MarketDetail } from "@/lib/api-types";

const loggerMock = {
  debug: vi.fn(),
  info: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
};

vi.mock("@/lib/logging", () => ({
  logger: loggerMock,
}));

describe("fetchMarketByEventId", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("normalizes resolution metadata and fallbacks", async () => {
    const payload = {
      event_id: "evt-detail",
      title: "Detail Market",
      category: "Crypto",
      oracle: "0xoracle",
      created_at: "2024-05-01T00:00:00.000Z",
      updated_at: "2024-05-02T00:00:00.000Z",
      outcomes: ["Yes", "No"],
      outcome_prices: [0.7, 0.3],
      extra_data: {
        gamma: {
          description: "Gamma description",
        },
        resolution: {
          resolved: true,
          payouts: [0, 1],
          winners: [{ index: 1, label: "No", payout: 1 }],
          checkedAt: "2024-05-03T00:00:00.000Z",
          blockNumber: 123,
          transactionHash: "0xabc",
        },
        heartbeat: {
          timestamp: "2024-05-04T00:00:00.000Z",
          latency_ms: 120,
        },
      },
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => payload,
    });
    vi.stubGlobal("fetch", fetchMock);

    const { fetchMarketByEventId } = await import("@/lib/api");
    const detail = (await fetchMarketByEventId("evt-detail")) as MarketDetail;

    expect(detail.eventId).toBe("evt-detail");
    expect(detail.description).toBe("Gamma description");
    expect(detail.resolution?.resolved).toBe(true);
    expect(detail.resolution?.winners?.[0]).toEqual({ index: 1, label: "No", payout: 1 });
    expect(detail.heartbeat?.latencyMs).toBe(120);
    expect(fetchMock).toHaveBeenCalled();
    expect(fetchMock.mock.calls[0][0]).toContain("/events/evt-detail");
  });

  it("returns null and logs a warning when the market is missing", async () => {
    const originalFetch = globalThis.fetch;
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const { fetchMarketByEventId } = await import("@/lib/api");
    const result = await fetchMarketByEventId("missing");
    expect(result).toBeNull();
    expect(loggerMock.warn).toHaveBeenCalledWith("fetchMarketByEventId:not_found", { eventId: "missing" });
    globalThis.fetch = originalFetch;
  });

  it("returns null and logs errors on network failures", async () => {
    const originalFetch = globalThis.fetch;
    const fetchMock = vi.fn().mockRejectedValue(new Error("offline"));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const { fetchMarketByEventId } = await import("@/lib/api");
    const result = await fetchMarketByEventId("evt-error");
    expect(result).toBeNull();
    expect(loggerMock.error).toHaveBeenCalledWith("fetchMarketByEventId:error", {
      eventId: "evt-error",
      error: "offline",
    });
    globalThis.fetch = originalFetch;
  });
});
