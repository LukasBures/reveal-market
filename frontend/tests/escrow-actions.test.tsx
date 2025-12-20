import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { StakeQuoteCard } from "@/components/markets/StakeQuoteCard";

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

const hooks = vi.hoisted(() => ({
  useConnection: vi.fn(),
  useChainId: vi.fn(),
  useReadContract: vi.fn(),
  useWriteContract: vi.fn(),
  usePublicClient: vi.fn(),
}));

vi.mock("wagmi", async () => {
  return {
    defaultChain: mockDefaultChain,
    useConnection: hooks.useConnection,
    useChainId: hooks.useChainId,
    useReadContract: hooks.useReadContract,
    useWriteContract: hooks.useWriteContract,
    usePublicClient: hooks.usePublicClient,
  };
});

vi.mock("@/lib/wagmi", () => ({
  defaultChain: mockDefaultChain,
  wagmiConfig: {},
}));

vi.mock("@/hooks/useFxStream", () => ({
  useFxStream: () => ({
    fx: { zen_usd: 1, stale: false },
    status: "live",
    fxReceivedAt: new Date().toISOString(),
    ageSeconds: 1,
  }),
}));

vi.mock("@/lib/pricing-client", () => ({
  fetchPricingQuoteWithMeta: vi.fn().mockResolvedValue({
    stake_zen: 0.1,
    stake_wei: "100000000000000000",
    zen_usd: 1,
    zen_usd_scaled: "100000000",
    displayed_odds_multiplier: 1,
    rake_zen: 0,
    refund_zen: 0,
    hedge_usdc: 0,
    haircut_percent: 0,
    worsen_percent: 0,
    rake_percent: 0,
    total_monetisation: 0,
    chain_id: 2651420,
    quote_id: "q1",
    expires_at: new Date(Date.now() + 60_000).toISOString(),
    expiry_ts: Math.floor(Date.now() / 1000) + 60,
    signature: "0x",
    signer: "0x",
    market_id: "m1",
    user_id: "u1",
    wallet_address: "0xabc",
    outcome_id: 0,
    market_address: "0x1111111111111111111111111111111111111111",
  }),
  submitTrade: vi.fn(),
  FX_DEFAULT_PATH: "/fx/zen-usd",
}));

describe("Escrow funding guard", () => {
  beforeEach(() => {
    hooks.useConnection.mockReturnValue({ address: "0xabc", isConnected: true });
    hooks.useChainId.mockReturnValue(1); // wrong chain
    hooks.useReadContract.mockReturnValue({ data: 0n });
    hooks.useWriteContract.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue("0xhash") });
    hooks.usePublicClient.mockReturnValue({ waitForTransactionReceipt: vi.fn() });
  });

  it("blocks deposit/withdraw when on the wrong chain", async () => {
    render(
      <StakeQuoteCard
        marketAddress="0x1111111111111111111111111111111111111111"
        marketId="m1"
        outcomes={["Yes", "No"]}
        outcomePrices={[0.5, 0.5]}
      />,
    );

    const switchButton = screen.getByRole("button", { name: /switch to horizen/i });
    expect(switchButton).toBeDisabled();
    expect(screen.getByText(/switch to horizen testnet to trade/i)).toBeInTheDocument();
  });
});
