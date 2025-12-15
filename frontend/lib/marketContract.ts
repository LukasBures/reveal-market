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
  const quoteId = opts.quote.quote_id;
  if (!quoteId) {
    throw new Error("Quote id missing");
  }
  const quoteIdHex = quoteId.startsWith("0x") ? (quoteId as Hex) : (`0x${quoteId}` as Hex);
  const expirySeconds =
    typeof opts.quote.expiry_ts === "number" && Number.isFinite(opts.quote.expiry_ts) && opts.quote.expiry_ts > 0
      ? opts.quote.expiry_ts
      : opts.quote.expires_at
        ? Math.floor(Date.parse(opts.quote.expires_at) / 1000)
        : null;
  if (!expirySeconds || Number.isNaN(expirySeconds)) {
    throw new Error("Quote expiry missing");
  }
  const expiry = BigInt(expirySeconds);
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

export function useCommitWithQuote(contractAddress?: Address) {
  const { address } = useAccount();
  const chainId = useChainId();
  const { writeContractAsync, isPending, error } = useWriteContract();

  async function commitWithQuote(params: SignedQuoteParams) {
    if (!address) throw new Error("Wallet not connected");
    if (!contractAddress) throw new Error("Market contract address missing");
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

const revealMarketClaimAbi = [
  {
    "type": "function",
    "name": "claim",
    "stateMutability": "nonpayable",
    "inputs": [
      { "name": "user", "type": "address" },
      { "name": "ticketId", "type": "uint256" },
      { "name": "outcomeId", "type": "uint256" },
      { "name": "amount", "type": "uint256" },
      { "name": "salt", "type": "bytes32" },
      { "name": "merkleProof", "type": "bytes32[]" }
    ],
    "outputs": []
  }
] as const;

export type ClaimTicketParams = {
  marketAddress: Address;
  user: Address;
  ticketId: bigint;
  outcomeId: bigint;
  amountWei: bigint;
  salt: Hex;
  merkleProof: Hex[];
};

export function useClaimTicket() {
  const chainId = useChainId();
  const { writeContractAsync, isPending, error } = useWriteContract();

  async function claimTicket(params: ClaimTicketParams) {
    return writeContractAsync({
      address: params.marketAddress,
      abi: revealMarketClaimAbi,
      functionName: "claim",
      args: [params.user, params.ticketId, params.outcomeId, params.amountWei, params.salt, params.merkleProof],
      chainId,
    });
  }

  return { claimTicket, isPending, error };
}
