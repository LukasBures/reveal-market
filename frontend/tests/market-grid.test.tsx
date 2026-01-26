import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EventGrid } from "@/components/events/EventGrid";

const sampleMarkets = [
  {
    eventId: "evt-a",
    title: "A Event",
    category: "Politics",
    markets: [{ eventId: "evt-a", title: "A Market" }],
  },
  {
    eventId: "evt-b",
    title: "B Event",
    category: "Sports",
    markets: [{ eventId: "evt-b", title: "B Market" }],
  },
];

describe("EventGrid", () => {
  it("returns null when no events provided", () => {
    render(<EventGrid events={[]} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("renders one card per event", () => {
    render(<EventGrid events={sampleMarkets} />);
    expect(screen.getAllByRole("link")).toHaveLength(2);
  });
});
