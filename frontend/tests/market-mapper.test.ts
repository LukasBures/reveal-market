import { describe, expect, it } from "vitest";
import { mapApiMarketToSummary } from "@/lib/marketMapper";

describe("mapApiMarketToSummary", () => {
  it("maps extended metadata fields", () => {
    const payload = {
      event_id: "evt-123",
      title: "Test Market",
      status: "commit",
      starts_at: "2025-01-01T00:00:00Z",
      closes_at: "2025-01-02T00:00:00Z",
      orders_opened_at: "2024-12-31T20:00:00Z",
      resolution_source: "https://data.chain.link",
      market_maker: "0xabc",
      order_min_size: 5,
      price_tick_size: 0.01,
      enable_order_book: true,
      clob_token_ids: ["1", "2"],
      image_variants: ["primary.png", "fallback.png"],
      extra_data: {
        gamma: {
          image_url: "gamma.png",
          slug: "test-market",
        },
      },
    };

    const summary = mapApiMarketToSummary(payload);
    expect(summary.eventId).toBe("evt-123");
    expect(summary.startsAt).toBe("2025-01-01T00:00:00Z");
    expect(summary.closesAt).toBe("2025-01-02T00:00:00Z");
    expect(summary.ordersOpenedAt).toBe("2024-12-31T20:00:00Z");
    expect(summary.resolutionSource).toBe("https://data.chain.link");
    expect(summary.marketMaker).toBe("0xabc");
    expect(summary.orderMinSize).toBe(5);
    expect(summary.priceTickSize).toBe(0.01);
    expect(summary.enableOrderBook).toBe(true);
    expect(summary.clobTokenIds).toEqual(["1", "2"]);
    expect(summary.imageVariants).toEqual(["primary.png", "fallback.png"]);
  });
});
