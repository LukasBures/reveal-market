import { describe, expect, it } from "vitest";
import { resolveSupportedChains } from "@/lib/wallet/config";
import { base } from "wagmi/chains";

describe("resolveSupportedChains", () => {
  it("defaults to Base when the env var is missing", () => {
    expect(resolveSupportedChains(undefined)).toEqual([base]);
  });

  it("ignores unknown chain presets and falls back to Base", () => {
    expect(resolveSupportedChains("optimism,unknown")).toEqual([base]);
  });

  it("trims whitespace and keeps valid presets", () => {
    expect(resolveSupportedChains(" base ")).toEqual([base]);
  });
});
