import { describe, expect, it } from "vitest";
import { formatDate, formatDateTime, formatNumber, formatTime, formatUsd, formatUsdCompact } from "@/lib/formatters";

describe("formatters", () => {
  describe("formatNumber", () => {
    it("formats decimals with default options", () => {
      expect(formatNumber(12345.67)).toBe("12,345.67");
    });

    it("respects custom number formatting options", () => {
      expect(formatNumber(1234.567, { maximumFractionDigits: 1 })).toBe("1,234.6");
    });

    it("returns fallback for invalid values", () => {
      expect(formatNumber(NaN)).toBe("—");
      expect(formatNumber(undefined)).toBe("—");
    });
  });

  describe("formatUsd", () => {
    it("formats large dollar amounts without decimals", () => {
      expect(formatUsd(1234.56)).toBe("$1,235");
    });

    it("formats typical dollar amounts with cents", () => {
      expect(formatUsd(12.3456)).toBe("$12.35");
    });

    it("shows four decimals for small dollar values", () => {
      expect(formatUsd(0.1234)).toBe("$0.1234");
    });

    it("allows overriding fraction digits", () => {
      expect(formatUsd(50.1234, { maximumFractionDigits: 1 })).toBe("$50.1");
    });

    it("returns fallback for invalid dollar values", () => {
      expect(formatUsd(null)).toBe("—");
    });
  });

  describe("formatUsdCompact", () => {
    it("compacts large numbers to short notation", () => {
      expect(formatUsdCompact(125_000)).toBe("$125K");
    });

    it("accepts custom fraction digits", () => {
      expect(formatUsdCompact(1_234_567, { maximumFractionDigits: 2 })).toBe("$1.23M");
    });

    it("returns fallback for invalid compact numbers", () => {
      expect(formatUsdCompact(undefined)).toBe("—");
    });
  });

  describe("date and time formatting", () => {
    const timestamp = "2025-12-01T10:20:30Z";

    it("formats date and time together in UTC", () => {
      expect(formatDateTime(timestamp)).toBe("Dec 1, 2025 10:20");
    });

    it("respects 12 hour time formatting when requested", () => {
      expect(formatDateTime(timestamp, { hour12: true })).toBe("Dec 1, 2025 10:20 AM");
    });

    it("formats dates with fallback for invalid input", () => {
      expect(formatDate("2025-12-01T00:00:00Z")).toBe("Dec 1, 2025");
      expect(formatDate("not-a-date")).toBe("—");
    });

    it("formats times with overrides and fallback", () => {
      expect(formatTime(timestamp)).toBe("10:20:30");
      expect(formatTime(timestamp, { hour12: true })).toBe("10:20:30 AM");
      expect(formatTime(null)).toBe("—");
    });
  });
});
