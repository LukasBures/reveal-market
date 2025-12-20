import type { Address, Hex } from "viem";
import { useWriteContract, useChainId } from "wagmi";

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
  const { mutateAsync: writeContract, isPending, error } = useWriteContract();

  async function claimTicket(params: ClaimTicketParams) {
    return writeContract({
      address: params.marketAddress,
      abi: revealMarketClaimAbi,
      functionName: "claim",
      args: [params.user, params.ticketId, params.outcomeId, params.amountWei, params.salt, params.merkleProof],
      chainId,
    });
  }

  return { claimTicket, isPending, error };
}
