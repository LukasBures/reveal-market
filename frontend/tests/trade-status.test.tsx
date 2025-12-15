import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";
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
  useAccount: vi.fn(),
  useChainId: vi.fn(),
  useReadContract: vi.fn(),
  useWriteContract: vi.fn(),
  usePublicClient: vi.fn(),
}));

const pricingMocks = vi.hoisted(() => ({
  fetchPricingQuoteWithMeta: vi.fn(),
  fetchPricingPreview: vi.fn(),
  submitTrade: vi.fn(),
}));

vi.mock("wagmi", async () => {
  return {
    defaultChain: mockDefaultChain,
    useAccount: hooks.useAccount,
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
  fetchPricingQuoteWithMeta: pricingMocks.fetchPricingQuoteWithMeta,
  fetchPricingPreview: pricingMocks.fetchPricingPreview,
  submitTrade: pricingMocks.submitTrade,
  FX_DEFAULT_PATH: "/fx/zen-usd",
}));

const apiMocks = vi.hoisted(() => ({
  statusMock: vi.fn(),
}));
vi.mock("@/lib/api", () => ({
  fetchTradeStatus: apiMocks.statusMock,
}));

describe("Trade status polling", () => {
  it("polls trade status when tx hash is present", async () => {
    hooks.useAccount.mockReturnValue({ address: "0xabc", isConnected: true });
    hooks.useChainId.mockReturnValue(mockDefaultChain.id);
    hooks.useReadContract.mockReturnValue({ data: 0n });
    hooks.useWriteContract.mockReturnValue({ writeContractAsync: vi.fn() });
    hooks.usePublicClient.mockReturnValue({ waitForTransactionReceipt: vi.fn() });
    apiMocks.statusMock.mockResolvedValue({ status: "confirmed", txHash: "0xtx" });

    render(
      <StakeQuoteCard
        initialTxHash="0xtx"
        marketAddress="0x1111111111111111111111111111111111111111"
        marketId="m1"
        outcomes={["Yes", "No"]}
        outcomePrices={[0.5, 0.5]}
      />,
    );

    await waitFor(() => expect(apiMocks.statusMock).toHaveBeenCalledWith("0xtx"));
  });
});
