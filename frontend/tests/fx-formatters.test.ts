import { describe, expect, it } from "vitest";
import { formatEthUsd, formatZenUsd } from "@/lib/fx";

describe("fx formatters", () => {
  it("formats ZEN/USD values with fixed decimals", () => {
    expect(formatZenUsd(1.23456)).toBe("1.2346");
    expect(formatZenUsd(1.23)).toBe("1.2300");
  });

  it("supports custom decimal precision", () => {
    expect(formatZenUsd(0.98765, 2)).toBe("0.99");
  });

  it("returns null for invalid inputs", () => {
    expect(formatZenUsd(null)).toBeNull();
    expect(formatZenUsd(undefined)).toBeNull();
    expect(formatZenUsd(Number.NaN)).toBeNull();
  });

  it("keeps the legacy ETH formatter in sync", () => {
    expect(formatEthUsd(1.5)).toBe(formatZenUsd(1.5));
  });
});
