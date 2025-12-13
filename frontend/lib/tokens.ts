import type { Address } from "viem";
import { getAddress } from "viem";

const rawZen = (process.env.NEXT_PUBLIC_ZEN_TOKEN_ADDRESS ?? "").trim();

let normalizedZen: Address | null = null;
if (rawZen.length > 0) {
  try {
    normalizedZen = getAddress(rawZen);
  } catch {
    normalizedZen = null;
  }
}

export const ZEN_TOKEN_ADDRESS: Address | null = normalizedZen;

export function requireZenTokenAddress(): Address {
  if (!ZEN_TOKEN_ADDRESS) {
    throw new Error("ZEN token address is not configured (set NEXT_PUBLIC_ZEN_TOKEN_ADDRESS)");
  }
  return ZEN_TOKEN_ADDRESS;
}
