import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TradeSubmission } from "@/components/markets/TradeSubmission";

const defaultProps = {
  ctaLabel: "Buy Yes with 0.10 ZEN",
  submitBlockedReason: null,
  disabled: false,
  onSubmit: vi.fn(),
  txLoading: false,
  txError: null,
  txHash: null,
  txConfirmed: false,
  txStatus: null,
  relayerJobId: null,
  explorerBase: "https://horizen-testnet.explorer.caldera.xyz",
  error: null,
  stakeError: null,
  escrowInsufficient: false,
  fxStale: false,
  capExhausted: false,
  chainMismatch: false,
  chainName: "Horizen Testnet",
  expectedChainId: 2651420,
  tradingDisabled: false,
  tradingReason: null,
};

describe("TradeSubmission", () => {
  it("renders CTA button with label", () => {
    render(<TradeSubmission {...defaultProps} />);
    expect(screen.getByRole("button", { name: /buy yes with 0\.10 zen/i })).toBeInTheDocument();
  });

  it("button disabled when disabled=true", () => {
    render(<TradeSubmission {...defaultProps} disabled={true} />);
    expect(screen.getByRole("button")).toBeDisabled();
  });

  it("button disabled when submitBlockedReason is set", () => {
    render(
      <TradeSubmission
        {...defaultProps}
        disabled={true}
        submitBlockedReason="No wallet connected"
      />,
    );
    const button = screen.getByRole("button");
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent("No wallet connected");
  });

  it("shows blocked reason text instead of CTA label", () => {
    render(
      <TradeSubmission
        {...defaultProps}
        submitBlockedReason="Insufficient balance"
      />,
    );
    expect(screen.getByRole("button")).toHaveTextContent("Insufficient balance");
    expect(screen.queryByText(/buy yes/i)).not.toBeInTheDocument();
  });

  it("shows tx loading spinner state", () => {
    render(<TradeSubmission {...defaultProps} txLoading={true} />);
    expect(screen.getByText(/committing\.\.\./i)).toBeInTheDocument();
  });

  it("shows tx error message", () => {
    render(
      <TradeSubmission
        {...defaultProps}
        txError="Transaction reverted"
      />,
    );
    expect(screen.getByText("Transaction reverted")).toBeInTheDocument();
  });

  it("shows confirmed tx with explorer link", () => {
    const txHash = `0x${"a".repeat(64)}`;
    render(
      <TradeSubmission
        {...defaultProps}
        txHash={txHash}
        txConfirmed={true}
        txStatus="confirmed"
      />,
    );
    expect(screen.getByText(/commit confirmed on-chain/i)).toBeInTheDocument();
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute(
      "href",
      `https://horizen-testnet.explorer.caldera.xyz/tx/${txHash}`,
    );
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("shows relayer job ID when no tx hash", () => {
    render(
      <TradeSubmission
        {...defaultProps}
        relayerJobId="job-abc-123"
        txStatus="pending"
      />,
    );
    expect(screen.getByText(/job job-abc-123/i)).toBeInTheDocument();
    expect(screen.getByText(/waiting for the relayer/i)).toBeInTheDocument();
  });

  it("calls onSubmit when clicked", () => {
    const onSubmit = vi.fn();
    render(<TradeSubmission {...defaultProps} onSubmit={onSubmit} />);
    fireEvent.click(screen.getByRole("button"));
    expect(onSubmit).toHaveBeenCalledOnce();
  });

  it("shows 'trading disabled' warning when tradingDisabled=true", () => {
    render(
      <TradeSubmission
        {...defaultProps}
        tradingDisabled={true}
        tradingReason="Market is paused"
      />,
    );
    expect(screen.getByText("Market is paused")).toBeInTheDocument();
  });

  it("does NOT show warning when tradingReason='Market settled'", () => {
    render(
      <TradeSubmission
        {...defaultProps}
        tradingDisabled={true}
        tradingReason="Market settled"
      />,
    );
    expect(screen.queryByText("Market settled")).not.toBeInTheDocument();
  });

  it("shows default unavailable message when tradingDisabled=true and no reason", () => {
    render(
      <TradeSubmission
        {...defaultProps}
        tradingDisabled={true}
        tradingReason={null}
      />,
    );
    expect(screen.getByText("Trading is unavailable for this market.")).toBeInTheDocument();
  });

  it("shows chain mismatch warning", () => {
    render(
      <TradeSubmission
        {...defaultProps}
        chainMismatch={true}
      />,
    );
    expect(
      screen.getByText(/switch to horizen testnet \(chain 2651420\) to trade/i),
    ).toBeInTheDocument();
  });

  it("shows escrow insufficient warning", () => {
    render(
      <TradeSubmission
        {...defaultProps}
        escrowInsufficient={true}
      />,
    );
    expect(screen.getByText(/deposit to escrow/i)).toBeInTheDocument();
    const dashLink = screen.getByRole("link", { name: /dashboard/i });
    expect(dashLink).toHaveAttribute("href", "/dashboard");
  });

  it("shows FX stale warning", () => {
    render(
      <TradeSubmission
        {...defaultProps}
        fxStale={true}
      />,
    );
    expect(screen.getByText(/pricing paused due to stale fx/i)).toBeInTheDocument();
  });

  it("shows cap exhausted warning", () => {
    render(
      <TradeSubmission
        {...defaultProps}
        capExhausted={true}
      />,
    );
    expect(screen.getByText(/stake cap reached/i)).toBeInTheDocument();
  });
});
