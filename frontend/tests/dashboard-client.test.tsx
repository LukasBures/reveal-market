import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { encodePacked, keccak256 } from "viem";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DashboardClient } from "@/components/dashboard/DashboardClient";

const mockDefaultChain = vi.hoisted(() => ({
  id: 2651420,
  name: "Horizen Testnet",
  nativeCurrency: { name: "Zen", symbol: "ZEN", decimals: 18 },
  rpcUrls: {
    default: { http: ["https://horizen-testnet.rpc.caldera.xyz/http"] },
    public: { http: ["https://horizen-testnet.rpc.caldera.xyz/http"] },
  },
  blockExplorers: { default: { name: "Explorer", url: "https://horizen-testnet.explorer.caldera.xyz" } },
})) as const;

const hoisted = vi.hoisted(() => ({
  useConnection: vi.fn(),
  useChainId: vi.fn(),
  fetchPositions: vi.fn(),
  fetchClaimBundles: vi.fn(),
  fetchMarketByEventId: vi.fn(),
  useWriteContract: vi.fn(),
  useReadContract: vi.fn(),
  usePublicClient: vi.fn(),
  useSignMessage: vi.fn(),
}));

vi.mock("wagmi", async () => {
  const actual = await vi.importActual<typeof import("wagmi")>("wagmi");
  return {
    ...actual,
    defaultChain: mockDefaultChain,
    useConnection: hoisted.useConnection,
    useChainId: hoisted.useChainId,
    useWriteContract: hoisted.useWriteContract,
    useReadContract: hoisted.useReadContract,
    usePublicClient: hoisted.usePublicClient,
    useSignMessage: hoisted.useSignMessage,
  };
});

vi.mock("@/lib/wagmi", () => ({
  defaultChain: mockDefaultChain,
  wagmiConfig: {},
}));

vi.mock("@/lib/api", () => ({
  fetchPositions: hoisted.fetchPositions,
  fetchClaimBundles: hoisted.fetchClaimBundles,
  fetchMarketByEventId: hoisted.fetchMarketByEventId,
}));

describe("DashboardClient", () => {
  beforeEach(() => {
    hoisted.useConnection.mockReset();
    hoisted.useChainId.mockReset();
    hoisted.fetchPositions.mockReset();
    hoisted.fetchClaimBundles.mockReset();
    hoisted.fetchMarketByEventId.mockReset();
    hoisted.useWriteContract.mockReset();
    hoisted.useReadContract.mockReset();
    hoisted.usePublicClient.mockReset();
    hoisted.useSignMessage.mockReset();
    hoisted.useSignMessage.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue("0xsig") });
    hoisted.useReadContract.mockReturnValue({ data: 0n });
    hoisted.useWriteContract.mockReturnValue({
      mutateAsync: vi.fn(),
      isPending: false,
      error: undefined,
    });
  });

  it("prompts to connect when wallet is disconnected", () => {
    hoisted.useConnection.mockReturnValue({ address: undefined, isConnected: false });
    hoisted.useChainId.mockReturnValue(undefined);

    render(<DashboardClient />);

    expect(screen.getByText(/connect your wallet/i)).toBeInTheDocument();
  });

  it("renders positions and triggers claim action", async () => {
    hoisted.useConnection.mockReturnValue({
      address: "0x9999999999999999999999999999999999999999",
      isConnected: true,
    });
    hoisted.useChainId.mockReturnValue(2651420);
    const writeContract = vi.fn().mockResolvedValue("0xclaim");
    hoisted.useWriteContract.mockReturnValue({
      mutateAsync: writeContract,
      isPending: false,
      error: undefined,
    });
    hoisted.useReadContract.mockReturnValue({ data: 0n });
    hoisted.usePublicClient.mockReturnValue({ waitForTransactionReceipt: vi.fn() });
    hoisted.useSignMessage.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue("0xsig") });
    hoisted.fetchMarketByEventId.mockResolvedValue({
      outcomes: ["Yes", "No"],
    });
    hoisted.fetchPositions.mockResolvedValue({
      positions: [
        {
          market_id: "m-1",
          market_title: "Yes/No",
          outcome_id: 0,
          stake_wei: "100000000000000000",
          stake_zen: 0.1,
          status: "settled",
          ticket_id: 0,
          claimable: true,
          created_at: "2024-01-01T00:00:00Z",
          merkle_root: "0x" + "ab" * 32,
          closes_at: "2024-01-02T00:00:00Z",
        },
      ],
      escrowBalance: "100000000000000000",
    });
    const salt = "0x" + "00".repeat(32);
    const user = "0x9999999999999999999999999999999999999999";
    const userSalt = keccak256(
      encodePacked(["address", "bytes32"], [user as `0x${string}`, salt as `0x${string}`]),
    );
    const leaf = keccak256(
      encodePacked(
        ["uint256", "uint256", "uint256", "bytes32"],
        [0n, 0n, 100000000000000000n, userSalt as `0x${string}`],
      ),
    );
    hoisted.fetchClaimBundles.mockResolvedValue({
      bundles: [
        {
          marketId: "m-1",
          marketAddress: "0x1111111111111111111111111111111111111111",
          commitmentsRoot: leaf,
          ticketId: 0,
          outcomeId: 0,
          amountWei: "100000000000000000",
          salt,
          merkleProof: [],
          leaf,
          user,
        },
      ],
    });

    render(<DashboardClient />);

    await waitFor(() => expect(screen.getByText(/balance: 0\.100 zen/i)).toBeInTheDocument());
    expect(screen.getByText(/yes\/no/i)).toBeInTheDocument();
    expect(screen.getAllByText(/claimable/i)[0]).toBeInTheDocument();
    await waitFor(() => expect(hoisted.fetchMarketByEventId).toHaveBeenCalledWith("m-1"));
    expect(screen.getByText(/outcome: yes/i)).toBeInTheDocument();

    const claimButton = screen.getAllByRole("button").find((btn) => btn.textContent?.trim().toLowerCase() === "claim");
    expect(claimButton).toBeTruthy();
    fireEvent.click(claimButton!);
    await waitFor(() => expect(writeContract).toHaveBeenCalledTimes(1));
    expect(hoisted.fetchPositions).toHaveBeenCalledTimes(2);
    expect(hoisted.fetchClaimBundles).toHaveBeenCalledTimes(2);
  });
});
