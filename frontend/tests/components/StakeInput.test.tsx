import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { StakeInput } from "@/components/markets/StakeInput";

const binaryProps = {
  outcomes: ["Yes", "No"],
  outcomePrices: [0.65, 0.35],
  selectedOutcome: 0,
  stakeZen: 0.1,
  ticketSize: 0.1,
  tradingDisabled: false,
  onOutcomeSelect: vi.fn(),
};

const multiProps = {
  outcomes: ["Red", "Blue", "Green"],
  outcomePrices: [0.4, 0.35, 0.25],
  selectedOutcome: 0,
  stakeZen: 0.1,
  ticketSize: 0.1,
  tradingDisabled: false,
  onOutcomeSelect: vi.fn(),
};

describe("StakeInput", () => {
  it("renders binary outcomes (2 columns)", () => {
    render(<StakeInput {...binaryProps} />);
    expect(screen.getByText(/buy yes/i)).toBeInTheDocument();
    expect(screen.getByText(/buy no/i)).toBeInTheDocument();
    // Binary layout uses a 2-column grid; both should be buttons
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(2);
  });

  it("renders multi-outcome layout (3+ outcomes)", () => {
    render(<StakeInput {...multiProps} />);
    expect(screen.getByText("Red")).toBeInTheDocument();
    expect(screen.getByText("Blue")).toBeInTheDocument();
    expect(screen.getByText("Green")).toBeInTheDocument();
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(3);
  });

  it("shows outcome prices as percentages", () => {
    render(<StakeInput {...binaryProps} />);
    // 0.65 -> 65%, 0.35 -> 35%
    expect(screen.getByText("65%")).toBeInTheDocument();
    expect(screen.getByText("35%")).toBeInTheDocument();
  });

  it("highlights selected outcome", () => {
    const { container } = render(<StakeInput {...binaryProps} selectedOutcome={0} />);
    const buttons = container.querySelectorAll("button");
    // The first button (Yes, index 0) should have the active/emerald style
    expect(buttons[0].className).toContain("border-emerald-400");
    // The second button (No, index 1) should NOT have the active style
    expect(buttons[1].className).not.toContain("border-rose-400");
  });

  it("highlights No outcome when selected", () => {
    const { container } = render(<StakeInput {...binaryProps} selectedOutcome={1} />);
    const buttons = container.querySelectorAll("button");
    // The second button (No, index 1) should have the active/rose style
    expect(buttons[1].className).toContain("border-rose-400");
    // The first button (Yes, index 0) should NOT have the active style
    expect(buttons[0].className).not.toContain("border-emerald-400");
  });

  it("calls onOutcomeSelect when outcome clicked", () => {
    const onOutcomeSelect = vi.fn();
    render(<StakeInput {...binaryProps} onOutcomeSelect={onOutcomeSelect} />);
    fireEvent.click(screen.getByText(/buy no/i));
    expect(onOutcomeSelect).toHaveBeenCalledWith(1);
  });

  it("calls onOutcomeSelect with correct index for multi-outcome", () => {
    const onOutcomeSelect = vi.fn();
    render(<StakeInput {...multiProps} onOutcomeSelect={onOutcomeSelect} />);
    fireEvent.click(screen.getByText("Green"));
    expect(onOutcomeSelect).toHaveBeenCalledWith(2);
  });

  it("shows disabled state when tradingDisabled=true", () => {
    render(<StakeInput {...binaryProps} tradingDisabled={true} />);
    const buttons = screen.getAllByRole("button");
    for (const button of buttons) {
      expect(button).toBeDisabled();
      expect(button.className).toContain("cursor-not-allowed");
      expect(button.className).toContain("opacity-60");
    }
  });

  it("displays ticket size", () => {
    render(<StakeInput {...binaryProps} ticketSize={0.1} />);
    expect(screen.getByDisplayValue("0.10 ZEN")).toBeInTheDocument();
    expect(screen.getByText(/fixed ticket size/i)).toBeInTheDocument();
  });

  it("shows stake ZEN value with different ticket size", () => {
    render(<StakeInput {...binaryProps} ticketSize={1.5} />);
    expect(screen.getByDisplayValue("1.50 ZEN")).toBeInTheDocument();
  });

  it("falls back to Yes/No when outcomes array is empty", () => {
    render(<StakeInput {...binaryProps} outcomes={[]} />);
    expect(screen.getByText(/buy yes/i)).toBeInTheDocument();
    expect(screen.getByText(/buy no/i)).toBeInTheDocument();
  });
});
