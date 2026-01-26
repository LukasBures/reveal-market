import { render, screen } from "@testing-library/react";
import React from "react";
import { MarketDetailMetadata } from "@/components/markets/MarketDetailMetadata";
import type { MarketDetail } from "@/lib/api-types";
import { afterEach } from "vitest";

const baseMarket: MarketDetail = {
  eventId: "evt-1",
  title: "Will the Fed cut rates?",
  category: "macro",
  tags: ["fed", "macro"],
  status: "commit",
  commitDeadline: "2025-12-01T00:00:00.000Z",
  revealDeadline: "2025-12-05T00:00:00.000Z",
  outcomes: ["Yes", "No"],
  outcomePrices: [0.45, 0.55],
  imageUrl: null,
  slug: "fed-cut-rates",
  umaStatus: "resolved",
  oracle: "UMA",
  marketAddress: "0x123",
  createdAt: "2025-11-01T00:00:00.000Z",
  updatedAt: "2025-11-02T00:00:00.000Z",
  extraData: { description: "Mirror" },
};

const originalExplorer = process.env.NEXT_PUBLIC_BLOCK_EXPLORER_URL;

afterEach(() => {
  process.env.NEXT_PUBLIC_BLOCK_EXPLORER_URL = originalExplorer;
});

describe("MarketDetailMetadata", () => {
  it("renders core identifiers and tags", () => {
    render(<MarketDetailMetadata market={baseMarket} />);

    expect(screen.getByText("Identifiers & provenance")).toBeInTheDocument();
    expect(screen.getByText(baseMarket.marketAddress!)).toBeInTheDocument();
    expect(screen.getByText("#fed")).toBeInTheDocument();
    expect(screen.getByText("#macro")).toBeInTheDocument();
  });

  it("links addresses to the explorer", () => {
    process.env.NEXT_PUBLIC_BLOCK_EXPLORER_URL = "https://explorer.testnet/";

    render(<MarketDetailMetadata market={baseMarket} />);

    expect(screen.getByRole("link", { name: baseMarket.marketAddress! })).toHaveAttribute(
      "href",
      "https://explorer.testnet/address/0x123",
    );
    expect(screen.getByRole("button", { name: "Copy Copy" })).toBeInTheDocument();
  });

  it("renders CLOB metadata plus rake", () => {
    const market: MarketDetail = {
      ...baseMarket,
      rakeBps: 149.6,
      extraData: {
        ...(baseMarket.extraData ?? {}),
        gamma: {
          clobTokenIds: [111, "222"],
          clobPairId: "pair-999",
        },
      },
    };

    render(<MarketDetailMetadata market={market} />);

    expect(screen.getByText("pair-999")).toBeInTheDocument();
    expect(screen.getByText("111, 222")).toBeInTheDocument();
    expect(screen.getByText("150 bps")).toBeInTheDocument();
  });

  it("links resolver URLs and renders resolution winners", () => {
    process.env.NEXT_PUBLIC_BLOCK_EXPLORER_URL = "https://explorer.testnet/";
    const market: MarketDetail = {
      ...baseMarket,
      resolutionSource: "https://resolver.example.com/market/evt-1",
      resolution: {
        resolved: true,
        winners: [
          { index: 1, label: "Outcome B", payout: 0.42 },
          { index: 0, payout: 0.5 },
        ],
        checkedAt: "2025-12-01T10:00:00Z",
        transactionHash: "0xfeedface",
      },
    };

    render(<MarketDetailMetadata market={market} />);

    expect(screen.getByRole("link", { name: "https://resolver.example.com/market/evt-1" })).toHaveAttribute(
      "href",
      "https://resolver.example.com/market/evt-1",
    );
    expect(screen.getByText("Outcome B")).toBeInTheDocument();
    expect(screen.getByText(/42%/)).toBeInTheDocument();
    expect(screen.getByText(/Outcome 0/)).toBeInTheDocument();
    expect(screen.getByText("Dec 1, 2025 10:00")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "0xfeedface" })).toHaveAttribute(
      "href",
      "https://explorer.testnet/tx/0xfeedface",
    );
  });

  it("renders resolution transaction details with explorer link and block number", () => {
    process.env.NEXT_PUBLIC_BLOCK_EXPLORER_URL = "https://explorer.testnet/";
    const market: MarketDetail = {
      ...baseMarket,
      resolution: {
        resolved: true,
        transactionHash: "0xdeadbeef",
        blockNumber: 99,
      },
    };

    render(<MarketDetailMetadata market={market} />);

    expect(screen.getByRole("link", { name: "0xdeadbeef" })).toHaveAttribute(
      "href",
      "https://explorer.testnet/tx/0xdeadbeef",
    );
    expect(screen.getByText("Block #99")).toBeInTheDocument();
  });

  it("hides tags when metadata missing", () => {
    const market: MarketDetail = {
      ...baseMarket,
      tags: [],
      slug: undefined,
      marketAddress: undefined,
    };

    render(<MarketDetailMetadata market={market} />);

    expect(screen.queryByText("#fed")).not.toBeInTheDocument();
    expect(screen.queryByText(baseMarket.marketAddress!)).not.toBeInTheDocument();
  });
});
