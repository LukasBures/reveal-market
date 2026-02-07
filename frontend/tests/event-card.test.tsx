import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EventCard } from "@/components/events/EventCard";

describe("EventCard", () => {
  it("renders the binary gauge card for yes/no markets", () => {
    render(
      <EventCard
        event={{
          eventId: "evt-yes-no",
          title: "Will it rain?",
          markets: [
            {
              eventId: "evt-yes-no",
              title: "Will it rain?",
              outcomes: ["Yes", "No"],
              outcomePrices: [0.62, 0.38],
            },
          ],
        }}
      />,
    );

    expect(screen.getByText(/chance/i)).toBeInTheDocument();
    expect(screen.getByText("Yes")).toBeInTheDocument();
    expect(screen.getByText("No")).toBeInTheDocument();
  });

  it("renders the head-to-head card for non-yes/no binary markets", () => {
    render(
      <EventCard
        event={{
          eventId: "evt-h2h",
          title: "Seahawks vs Patriots",
          markets: [
            {
              eventId: "evt-h2h",
              title: "Seahawks vs Patriots",
              outcomes: ["Seahawks", "Patriots"],
              outcomePrices: [0.7, 0.3],
            },
          ],
        }}
      />,
    );

    expect(screen.queryByText(/chance/i)).not.toBeInTheDocument();
    expect(screen.getAllByText("Seahawks")).toHaveLength(2);
    expect(screen.getAllByText("Patriots")).toHaveLength(2);
  });

  it("renders the multi-outcome card for non-binary events", () => {
    render(
      <EventCard
        event={{
          eventId: "evt-multi",
          title: "Fed decision",
          markets: [
            { eventId: "evt-multi-a", title: "25 bps decrease", outcomePrices: [0.1] },
            { eventId: "evt-multi-b", title: "No change", outcomePrices: [0.8] },
            { eventId: "evt-multi-c", title: "25 bps increase", outcomePrices: [0.1] },
          ],
        }}
      />,
    );

    expect(screen.getByText("3 markets")).toBeInTheDocument();
    expect(screen.getByText("Fed decision")).toBeInTheDocument();
  });

  it("uses a head-to-head market for sports events with multiple markets", () => {
    render(
      <EventCard
        event={{
          eventId: "evt-sports",
          title: "Trail Blazers vs Wizards",
          category: "Sports",
          markets: [
            {
              eventId: "evt-sports-main",
              title: "Trail Blazers vs Wizards",
              outcomes: ["Trail Blazers", "Wizards"],
              outcomePrices: [0.71, 0.29],
            },
            {
              eventId: "evt-sports-alt",
              title: "Spread -8.5",
              outcomes: ["Yes", "No"],
              outcomePrices: [0.44, 0.56],
            },
          ],
        }}
      />,
    );

    expect(screen.getAllByText("Trail Blazers")).toHaveLength(2);
    expect(screen.getAllByText("Wizards")).toHaveLength(2);
    expect(screen.queryByText(/markets/i)).not.toBeInTheDocument();
  });
});
