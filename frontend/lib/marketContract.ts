import type { Address, Hex } from "viem";
import { toHex } from "viem";
import { useAccount, useWriteContract, useChainId } from "wagmi";
import type { PricingQuote } from "./pricing-client";

// Minimal ABI for commitWithQuote(outcomeId, amount, salt, SignedQuote)
const revealMarketAbi = [
  {
    "type": "function",
    "name": "commitWithQuote",
    "stateMutability": "nonpayable",
    "inputs": [
      { "name": "outcomeId", "type": "uint256" },
      { "name": "amount", "type": "uint256" },
      { "name": "salt", "type": "bytes32" },
      {
        "name": "quote",
        "type": "tuple",
        "components": [
          { "name": "quoteId", "type": "bytes32" },
          { "name": "stakeZen", "type": "uint256" },
          { "name": "zenUsd", "type": "uint256" },
          { "name": "expiry", "type": "uint256" },
          { "name": "outcomeId", "type": "uint256" },
          { "name": "expectedUser", "type": "address" },
          { "name": "signature", "type": "bytes" }
        ]
      }
    ],
    "outputs": []
  }
] as const;

export type SignedQuoteParams = {
  outcomeId: bigint;
  amountWei: bigint;
  salt: Hex;
  quote: {
    quoteId: Hex;
    stakeZen: bigint;
    zenUsd: bigint;
    expiry: bigint;
    outcomeId: bigint;
    expectedUser: Address;
    signature: Hex;
  };
};

export function buildSignedQuoteParams(opts: {
  quote: PricingQuote;
  outcomeId: number;
  walletAddress: Address;
  amountWei?: bigint;
  salt?: Hex;
}): SignedQuoteParams {
  const saltHex = opts.salt ?? toHex(crypto.getRandomValues(new Uint8Array(32)));
  const quoteIdHex =
    opts.quote.quote_id.startsWith("0x") ? (opts.quote.quote_id as Hex) : (`0x${opts.quote.quote_id}` as Hex);
  const expiry = BigInt(opts.quote.expiry_ts ?? Math.floor(new Date(opts.quote.expires_at).getTime() / 1000));
  // Contracts expect stake in wei and FX scaled by 1e8; keep units consistent with backend signatures.
  const stakeWei = BigInt(opts.amountWei ?? BigInt(opts.quote.stake_wei));
  const zenUsdScaled = BigInt(opts.quote.zen_usd_scaled);
  return {
    outcomeId: BigInt(opts.outcomeId),
    amountWei: stakeWei,
    salt: saltHex,
    quote: {
      quoteId: quoteIdHex,
      stakeZen: stakeWei,
      zenUsd: zenUsdScaled,
      expiry,
      outcomeId: BigInt(opts.outcomeId),
      expectedUser: opts.walletAddress,
      signature: opts.quote.signature as Hex,
    },
  };
}

export function useCommitWithQuote(contractAddress: Address) {
  const { address } = useAccount();
  const chainId = useChainId();
  const { writeContractAsync, isPending, error } = useWriteContract();

  async function commitWithQuote(params: SignedQuoteParams) {
    if (!address) throw new Error("Wallet not connected");
    return writeContractAsync({
      address: contractAddress,
      abi: revealMarketAbi,
      functionName: "commitWithQuote",
      args: [params.outcomeId, params.amountWei, params.salt, params.quote],
      chainId
    });
  }

  return { commitWithQuote, isPending, error };
}
