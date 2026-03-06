import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { QuoteDisplay } from "@/components/markets/QuoteDisplay";
import type { PricingQuote } from "@/lib/pricing-client";

const baseQuote: PricingQuote = {
  stake_zen: 0.1,
  stake_wei: "100000000000000000",
  zen_usd: 1,
  zen_usd_scaled: "100000000",
  displayed_odds_multiplier: 1,
  rake_zen: 0.002,
  refund_zen: 0,
  hedge_usdc: 0,
  haircut_percent: 0,
  worsen_percent: 0,
  rake_percent: 2,
  total_monetisation: 2,
  chain_id: 2651420,
  quote_id: "q-abcdef123456",
  expires_at: new Date(Date.now() + 60_000).toISOString(),
  expiry_ts: Math.floor(Date.now() / 1000) + 60,
  signature: "0xsig",
  signer: "0xsigner",
  market_id: "m1",
  user_id: "u1",
  wallet_address: "0xabc",
  outcome_id: 0,
  market_address: "0x1111111111111111111111111111111111111111",
  remaining_user_stake_zen: 0.9,
  remaining_market_stake_zen: 4.5,
  max_user_stake_per_market_zen: 1.0,
  max_market_stake_zen: 5.0,
};

const defaultProps = {
  quote: baseQuote,
  toWinZen: 0.154,
  stakeZen: 0.1,
  quoteCountdown: "0:45",
  shortQuoteId: "q-abcdef",
  quoteExpiryMs: Date.now() + 60_000,
};

describe("QuoteDisplay", () => {
  it("renders 'to win' value", () => {
    render(<QuoteDisplay {...defaultProps} />);
    expect(screen.getByText("To win")).toBeInTheDocument();
    expect(screen.getByText("0.1540 ZEN")).toBeInTheDocument();
  });

  it("shows shortened quote ID", () => {
    render(<QuoteDisplay {...defaultProps} />);
    expect(screen.getByText("q-abcdef")).toBeInTheDocument();
    expect(screen.getByText(/quote id/i)).toBeInTheDocument();
  });

  it("shows countdown timer", () => {
    render(<QuoteDisplay {...defaultProps} />);
    expect(screen.getByText(/expires in/i)).toBeInTheDocument();
    expect(screen.getByText(/0:45/)).toBeInTheDocument();
  });

  it("shows user/market caps when present", () => {
    render(<QuoteDisplay {...defaultProps} />);
    // user cap: remaining_user_stake_zen (0.9) + stake_zen (0.1) = 1.0, min(1.0, max=1.0) = 1.0000 ZEN
    // market cap: remaining_market_stake_zen (4.5) + stake_zen (0.1) = 4.6, min(4.6, max=5.0) = 4.6000 ZEN
    expect(screen.getByText(/caps/i)).toBeInTheDocument();
    expect(screen.getByText(/user:/i)).toBeInTheDocument();
    expect(screen.getByText(/1\.0000 ZEN/)).toBeInTheDocument();
    expect(screen.getByText(/4\.6000 ZEN/)).toBeInTheDocument();
  });

  it("handles null quote gracefully", () => {
    render(
      <QuoteDisplay
        quote={null}
        toWinZen={null}
        stakeZen={0}
        quoteCountdown={null}
        shortQuoteId={null}
        quoteExpiryMs={null}
      />,
    );
    // Should still render the "To win" metric, but with a dash for NaN
    expect(screen.getByText("To win")).toBeInTheDocument();
    // formatNumber(NaN) returns "—"
    expect(screen.getByText(/— ZEN/)).toBeInTheDocument();
    // No quote-specific elements
    expect(screen.queryByText(/quote id/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/expires in/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/caps/i)).not.toBeInTheDocument();
  });

  it("handles undefined toWinZen gracefully", () => {
    render(
      <QuoteDisplay
        quote={null}
        toWinZen={undefined as unknown as number | null}
        stakeZen={0}
        quoteCountdown={null}
        shortQuoteId={null}
        quoteExpiryMs={null}
      />,
    );
    expect(screen.getByText("To win")).toBeInTheDocument();
    expect(screen.getByText(/— ZEN/)).toBeInTheDocument();
  });

  it("shows zero values without crashing", () => {
    const zeroQuote: PricingQuote = {
      ...baseQuote,
      stake_zen: 0,
      remaining_user_stake_zen: 0,
      remaining_market_stake_zen: 0,
    };
    render(
      <QuoteDisplay
        quote={zeroQuote}
        toWinZen={0}
        stakeZen={0}
        quoteCountdown="0:00"
        shortQuoteId="q-zero"
        quoteExpiryMs={Date.now()}
      />,
    );
    expect(screen.getByText("To win")).toBeInTheDocument();
    expect(screen.getByText("0.0000 ZEN")).toBeInTheDocument();
    expect(screen.getByText("q-zero")).toBeInTheDocument();
  });

  it("shows stake and win summary line when quote is present", () => {
    render(<QuoteDisplay {...defaultProps} />);
    expect(screen.getByText(/stake 0\.1000 zen/i)).toBeInTheDocument();
    expect(screen.getByText(/win 0\.1540 zen/i)).toBeInTheDocument();
  });

  it("uses 'preview' fallback when shortQuoteId is null but quote is present", () => {
    render(
      <QuoteDisplay
        {...defaultProps}
        shortQuoteId={null}
      />,
    );
    expect(screen.getByText(/preview/i)).toBeInTheDocument();
    expect(screen.queryByText(/quote id/i)).not.toBeInTheDocument();
  });
});
