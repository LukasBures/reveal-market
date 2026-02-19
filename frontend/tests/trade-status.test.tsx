import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { StakeQuoteCard } from "@/components/markets/StakeQuoteCard";

const mockDefaultChain = vi.hoisted(
  () =>
    ({
      id: 2651420,
      name: "Horizen Testnet",
      nativeCurrency: { name: "Zen", symbol: "ZEN", decimals: 18 },
      rpcUrls: {
        default: { http: ["https://horizen-testnet.rpc.caldera.xyz/http"] },
        public: { http: ["https://horizen-testnet.rpc.caldera.xyz/http"] },
      },
      blockExplorers: { default: { name: "Explorer", url: "https://horizen-testnet.explorer.caldera.xyz" } },
    } as const),
);

const hooks = vi.hoisted(() => ({
  useConnection: vi.fn(),
  useChainId: vi.fn(),
  useReadContract: vi.fn(),
  useWriteContract: vi.fn(),
  usePublicClient: vi.fn(),
  useSignMessage: vi.fn(),
}));

const pricingMocks = vi.hoisted(() => ({
  fetchPricingQuoteWithMeta: vi.fn(),
  fetchPricingPreview: vi.fn(),
  submitTrade: vi.fn(),
}));

vi.mock("wagmi", async () => {
  return {
    defaultChain: mockDefaultChain,
    useConnection: hooks.useConnection,
    useChainId: hooks.useChainId,
    useReadContract: hooks.useReadContract,
    useWriteContract: hooks.useWriteContract,
    usePublicClient: hooks.usePublicClient,
    useSignMessage: hooks.useSignMessage,
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
  beforeEach(() => {
    vi.clearAllMocks();
    hooks.useSignMessage.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue("0xsig") });
  });

  it("calls fetchTradeStatus when tx hash is present", async () => {
    hooks.useConnection.mockReturnValue({ address: "0xabc", isConnected: true });
    hooks.useChainId.mockReturnValue(mockDefaultChain.id);
    hooks.useReadContract.mockReturnValue({ data: 0n });
    hooks.useWriteContract.mockReturnValue({ mutateAsync: vi.fn() });
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

    await waitFor(() => expect(apiMocks.statusMock).toHaveBeenCalledWith(undefined, "0xtx"));
  });

  it("omits market address when requesting preview without a market address", async () => {
    hooks.useConnection.mockReturnValue({ address: "0xabc", isConnected: true });
    hooks.useChainId.mockReturnValue(mockDefaultChain.id);
    hooks.useReadContract.mockReturnValue({ data: 0n });
    hooks.useWriteContract.mockReturnValue({ mutateAsync: vi.fn() });
    hooks.usePublicClient.mockReturnValue({ waitForTransactionReceipt: vi.fn() });
    pricingMocks.fetchPricingPreview.mockResolvedValue({
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
      chain_id: mockDefaultChain.id,
      quote_id: "q-preview",
      expires_at: new Date(Date.now() + 60_000).toISOString(),
      expiry_ts: Math.floor(Date.now() / 1000) + 60,
      signature: "0x",
      signer: "0x",
      market_id: "m1",
      user_id: "u1",
      wallet_address: "0xabc",
      outcome_id: 0,
      market_address: null,
    });

    render(
      <StakeQuoteCard marketId="m1" outcomes={["Yes", "No"]} outcomePrices={[0.5, 0.5]} />,
    );

    await waitFor(() => expect(pricingMocks.fetchPricingPreview).toHaveBeenCalled());
    const [, options] = pricingMocks.fetchPricingPreview.mock.calls[0];
    expect(options.marketAddress).toBeUndefined();
  });
});
