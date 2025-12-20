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

const rawEscrow = (process.env.NEXT_PUBLIC_RELAYER_ESCROW_ADDRESS ?? "").trim();
let normalizedEscrow: Address | null = null;
if (rawEscrow.length > 0) {
  try {
    normalizedEscrow = getAddress(rawEscrow);
  } catch {
    normalizedEscrow = null;
  }
}
export const RELAYER_ESCROW_ADDRESS: Address | null = normalizedEscrow;
