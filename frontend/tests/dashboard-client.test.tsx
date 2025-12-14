import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  useAccount: vi.fn(),
  useChainId: vi.fn(),
  fetchPositions: vi.fn(),
  submitClaim: vi.fn(),
}));

vi.mock("wagmi", async () => {
  const actual = await vi.importActual<typeof import("wagmi")>("wagmi");
  return {
    ...actual,
    defaultChain: mockDefaultChain,
    useAccount: hoisted.useAccount,
    useChainId: hoisted.useChainId,
  };
});

vi.mock("@/lib/wagmi", () => ({
  defaultChain: mockDefaultChain,
  wagmiConfig: {},
}));

vi.mock("@/lib/api", () => ({
  fetchPositions: hoisted.fetchPositions,
}));

vi.mock("@/lib/trade-client", () => ({
  submitClaim: hoisted.submitClaim,
}));

describe("DashboardClient", () => {
  beforeEach(() => {
    hoisted.useAccount.mockReset();
    hoisted.useChainId.mockReset();
    hoisted.fetchPositions.mockReset();
    hoisted.submitClaim.mockReset();
  });

  it("prompts to connect when wallet is disconnected", () => {
    hoisted.useAccount.mockReturnValue({ address: undefined, isConnected: false });
    hoisted.useChainId.mockReturnValue(undefined);

    render(<DashboardClient />);

    expect(screen.getByText(/connect your wallet/i)).toBeInTheDocument();
  });

  it("renders positions and triggers claim action", async () => {
    hoisted.useAccount.mockReturnValue({
      address: "0x9999999999999999999999999999999999999999",
      isConnected: true,
    });
    hoisted.useChainId.mockReturnValue(2651420);
    hoisted.fetchPositions.mockResolvedValue({
      positions: [
        {
          market_id: "m-1",
          market_title: "Yes/No",
          outcome_id: 0,
          stake_wei: 100000000000000000,
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
    hoisted.submitClaim.mockResolvedValue({ tx_hash: "0xclaim", status: "claimed" });

    render(<DashboardClient />);

    await waitFor(() => expect(screen.getByText(/balance: 0\.100 zen/i)).toBeInTheDocument());
    expect(screen.getByText(/yes\/no/i)).toBeInTheDocument();
    expect(screen.getByText(/claimable/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /claim/i }));
    await waitFor(() => expect(hoisted.submitClaim).toHaveBeenCalledTimes(1));
    expect(hoisted.submitClaim).toHaveBeenCalledWith("m-1", "0x9999999999999999999999999999999999999999", 0);
    expect(hoisted.fetchPositions).toHaveBeenCalledTimes(2);
  });
});
