import type { Address, Hex } from "viem";
import { useConnection, useWriteContract } from "wagmi";
import { defaultChain } from "./wagmi";

export const revealMarketClaimAbi = [
  {
    "type": "function",
    "name": "claim",
    "stateMutability": "nonpayable",
    "inputs": [
      { "name": "user", "type": "address" },
      { "name": "ticketId", "type": "uint256" },
      { "name": "outcomeId", "type": "uint256" },
      { "name": "amount", "type": "uint256" },
      { "name": "payout", "type": "uint256" },
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
  payoutWei: bigint;
  salt: Hex;
  merkleProof: Hex[];
  gasLimit?: bigint;
};

export function useClaimTicket() {
  const { address } = useConnection();
  const { mutateAsync: writeContract, isPending, error } = useWriteContract();

  async function claimTicket(params: ClaimTicketParams) {
    if (!address) {
      throw new Error("Wallet not connected");
    }
    return writeContract({
      address: params.marketAddress,
      abi: revealMarketClaimAbi,
      functionName: "claim",
      args: [
        params.user,
        params.ticketId,
        params.outcomeId,
        params.amountWei,
        params.payoutWei,
        params.salt,
        params.merkleProof,
      ],
      gas: params.gasLimit,
      chainId: defaultChain.id,
    });
  }

  return { claimTicket, isPending, error };
}
