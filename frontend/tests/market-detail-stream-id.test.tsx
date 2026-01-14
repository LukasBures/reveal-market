import { render } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";
import { MarketDetailOutcomes } from "@/components/markets/MarketDetailOutcomes";

const liveOutcomePricesMock = vi.hoisted(
  () =>
    vi.fn((..._args: unknown[]) => ({
      prices: [],
      streamError: null,
      fxStale: false,
    })),
);

const priceStreamStoreMock = vi.hoisted(
  () =>
    vi.fn((..._args: unknown[]) => ({
      connected: false,
      error: null,
      outcomes: [],
      histories: {},
      trades: [],
      transport: null,
      lastUpdated: null,
      fxStale: false,
      status: null,
      tickSize: undefined,
    })),
);

vi.mock("@/hooks/useLiveOutcomePrices", () => ({
  useLiveOutcomePrices: (...args: unknown[]) => liveOutcomePricesMock(...args),
}));

vi.mock("@/hooks/usePriceStreamConnection", () => ({
  usePriceStreamStore: (...args: unknown[]) => priceStreamStoreMock(...args),
  seedInitialOutcomes: vi.fn(),
}));

vi.mock("@/hooks/useFxStream", () => ({
  useFxStream: () => ({
    fx: { zen_usd: 1, stale: false },
    status: "live",
    fxReceivedAt: new Date().toISOString(),
    ageSeconds: 1,
  }),
}));

vi.mock("wagmi", () => ({
  useConnection: () => ({ address: undefined, connector: undefined, status: "disconnected" }),
  useChainId: () => 2651420,
  useSwitchChain: () => ({ mutate: vi.fn(), mutateAsync: vi.fn() }),
  useSignMessage: () => ({ mutateAsync: vi.fn().mockResolvedValue("0xsig") }),
}));

vi.mock("@/lib/wagmi", () => ({
  defaultChain: { id: 2651420, name: "Horizen Testnet" },
}));

vi.mock("@/lib/pricing-client", () => ({
  fetchPricingPreview: vi.fn(),
  fetchPricingQuoteWithMeta: vi.fn(),
  commitTrade: vi.fn(),
  fetchPriceHistory: vi.fn(),
  FX_DEFAULT_PATH: "/fx/zen-usd",
}));

describe("MarketDetailOutcomes stream id", () => {
  it("prefers conditionId for streamer subscriptions", () => {
    render(
      <MarketDetailOutcomes
        market={{
          eventId: "evt-1",
          conditionId: "cond-1",
          title: "Market",
          outcomes: ["Yes", "No"],
          outcomePrices: [0.5, 0.5],
        }}
      />,
    );

    expect(liveOutcomePricesMock.mock.calls[0][0]).toBe("cond-1");
    expect(priceStreamStoreMock.mock.calls[0][0]).toBe("cond-1");
  });
});
