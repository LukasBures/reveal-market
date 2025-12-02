import { describe, expect, it } from "vitest";
import { getCommitDeadline, getMarketVolume, resolvePriceStreamMarketId } from "@/lib/markets";

describe("markets helpers", () => {
  describe("getMarketVolume", () => {
    it("prefers reported 24h volume and clamps negatives", () => {
      expect(getMarketVolume({ volume24hUsd: 2500, orderbookVolumeUsd: 999 })).toBe(2500);
      expect(getMarketVolume({ volume24hUsd: -50, orderbookVolumeUsd: 999 })).toBe(0);
    });

    it("falls back to orderbook volume and handles string inputs", () => {
      expect(getMarketVolume({ volume24hUsd: undefined, orderbookVolumeUsd: "1234" as any })).toBe(1234);
    });

    it("returns zero when volume cannot be parsed", () => {
      expect(getMarketVolume({ volume24hUsd: "invalid" as any, orderbookVolumeUsd: null as any })).toBe(0);
    });
  });

  describe("getCommitDeadline", () => {
    it("returns the first non-empty deadline in priority order", () => {
      const base = {
        commitDeadline: "2025-01-01T00:00:00Z",
        closesAt: "2025-02-02T00:00:00Z",
        ordersOpenedAt: "2025-03-03T00:00:00Z",
        startsAt: "2025-04-04T00:00:00Z",
      };
      expect(getCommitDeadline(base)).toBe("2025-01-01T00:00:00Z");
      expect(
        getCommitDeadline({
          ...base,
          commitDeadline: "   ",
        }),
      ).toBe("2025-02-02T00:00:00Z");
      expect(
        getCommitDeadline({
          ...base,
          commitDeadline: undefined,
          closesAt: undefined,
        }),
      ).toBe("2025-03-03T00:00:00Z");
    });

    it("returns undefined when all candidates are missing", () => {
      expect(
        getCommitDeadline({
          commitDeadline: undefined,
          closesAt: undefined,
          ordersOpenedAt: undefined,
          startsAt: undefined,
        }),
      ).toBeUndefined();
    });
  });

  describe("resolvePriceStreamMarketId", () => {
    it("prefers condition id, then event id, then fallback", () => {
      expect(resolvePriceStreamMarketId({ conditionId: " cond-1 ", eventId: "evt-1" })).toBe("cond-1");
      expect(resolvePriceStreamMarketId({ conditionId: "", eventId: "evt-1" })).toBe("evt-1");
      expect(resolvePriceStreamMarketId({ conditionId: undefined, eventId: null }, "fallback")).toBe("fallback");
    });

    it("returns empty string when nothing is available", () => {
      expect(resolvePriceStreamMarketId({ conditionId: undefined, eventId: undefined })).toBe("");
    });
  });
});
