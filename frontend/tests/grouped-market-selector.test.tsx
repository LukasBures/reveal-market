import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { GroupedMarketSelector } from "@/components/markets/GroupedMarketSelector";
import type { MarketSibling } from "@/lib/api-types";

const siblings: MarketSibling[] = [
  {
    eventId: "evt-60000-a",
    title: "Will BTC dip to $60,000 by Friday?",
    groupItemThreshold: 60000,
    status: "open",
    outcomePrices: [0.51, 0.49],
    volume: 1000,
    commitDeadline: "2099-01-01T00:00:00.000Z",
  },
  {
    eventId: "evt-60000-b",
    title: "Will BTC dip to $60,000 by Saturday?",
    groupItemThreshold: 60000,
    status: "open",
    outcomePrices: [0.52, 0.48],
    volume: 900,
    commitDeadline: "2099-01-02T00:00:00.000Z",
  },
  {
    eventId: "evt-65000",
    title: "Will BTC dip to $65,000 by Friday?",
    groupItemThreshold: 65000,
    status: "open",
    outcomePrices: [0.6, 0.4],
    volume: 1200,
    commitDeadline: "2099-01-03T00:00:00.000Z",
  },
  {
    eventId: "evt-ended",
    title: "Will BTC dip to $55,000 by last week?",
    groupItemThreshold: 55000,
    status: "ended",
    outcomePrices: [0.3, 0.7],
    volume: 2000,
    commitDeadline: "2000-01-01T00:00:00.000Z",
  },
];

describe("GroupedMarketSelector", () => {
  it("keeps active sibling rows stable across selection changes", () => {
    const onSelect = vi.fn();

    const { rerender } = render(
      <GroupedMarketSelector
        groupSlug="bitcoin-dips"
        siblings={siblings}
        activeEventId="evt-60000-a"
        onSelectAction={onSelect}
      />,
    );

    // 3 active rows rendered, ended row is hidden behind toggle.
    expect(screen.getAllByRole("button").length).toBeGreaterThanOrEqual(4);
    expect(screen.getByText("Will BTC dip to $60,000 by Friday?")).toBeInTheDocument();
    expect(screen.getByText("Will BTC dip to $60,000 by Saturday?")).toBeInTheDocument();
    expect(screen.getByText("Will BTC dip to $65,000 by Friday?")).toBeInTheDocument();
    expect(screen.queryByText("Will BTC dip to $55,000 by last week?")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Will BTC dip to $60,000 by Saturday?"));
    expect(onSelect).toHaveBeenCalledWith("evt-60000-b");

    rerender(
      <GroupedMarketSelector
        groupSlug="bitcoin-dips"
        siblings={siblings}
        activeEventId="evt-60000-b"
        onSelectAction={onSelect}
      />,
    );

    // After selection changes, all active rows are still present.
    expect(screen.getByText("Will BTC dip to $60,000 by Friday?")).toBeInTheDocument();
    expect(screen.getByText("Will BTC dip to $60,000 by Saturday?")).toBeInTheDocument();
    expect(screen.getByText("Will BTC dip to $65,000 by Friday?")).toBeInTheDocument();
  });

  it("reveals ended rows only through the ended toggle", () => {
    render(
      <GroupedMarketSelector
        groupSlug="bitcoin-dips"
        siblings={siblings}
        activeEventId="evt-65000"
        onSelectAction={vi.fn()}
      />,
    );

    expect(screen.queryByText("Will BTC dip to $55,000 by last week?")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /show ended markets/i }));

    expect(screen.getByText("Will BTC dip to $55,000 by last week?")).toBeInTheDocument();
  });
});
