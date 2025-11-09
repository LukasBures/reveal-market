import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { FeaturedMarketsClient } from "@/components/markets/FeaturedMarketsClient";

const sampleMarket = {
  eventId: "evt-1",
  title: "Sample Market",
  category: "Politics",
  tags: ["gov"],
  outcomes: ["Yes", "No"],
  outcomePrices: [0.5, 0.5],
};

describe("FeaturedMarketsClient", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders skeletons when no markets exist yet", () => {
    const { container } = render(<FeaturedMarketsClient initialMarkets={[]} />);
    const skeletons = container.querySelectorAll(".animate-pulse");
    expect(skeletons.length).toBeGreaterThan(0);
  });

  it("renders markets and loads more on demand", async () => {
    const nextMarket = {
      eventId: "evt-2",
      title: "Second Market",
      category: "Sports",
      tags: [],
      outcomes: [],
      outcomePrices: [],
    };
    const fetchMock = global.fetch as unknown as vi.Mock;
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => [nextMarket],
    });

    render(
      <FeaturedMarketsClient
        initialMarkets={[sampleMarket]}
        pageSize={1}
        maxItems={3}
        searchQuery="sample"
      />,
    );

    expect(screen.getByText("Sample Market")).toBeInTheDocument();
    const button = screen.getByRole("button", { name: /load more markets/i });
    fireEvent.click(button);

    await waitFor(() => {
      expect(screen.getByText("Second Market")).toBeInTheDocument();
    });
    expect(fetchMock).toHaveBeenCalledWith("/markets?limit=1&offset=1&search=sample", { cache: "no-store" });
  });
});
