import type { Address } from "viem";
import { isAddress } from "viem";

const rawZen =
  (process.env.NEXT_PUBLIC_ZEN_TOKEN_ADDRESS ??
    process.env.ZEN_TOKEN_ADDRESS ??
    "").trim();

export const ZEN_TOKEN_ADDRESS: Address | null = isAddress(rawZen)
  ? (rawZen as Address)
  : null;

export function requireZenTokenAddress(): Address {
  if (!ZEN_TOKEN_ADDRESS) {
    throw new Error("ZEN token address is not configured (set NEXT_PUBLIC_ZEN_TOKEN_ADDRESS)");
  }
  return ZEN_TOKEN_ADDRESS;
}
