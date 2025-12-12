import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import type { Mock } from "vitest";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { FeaturedMarketsClient, AUTO_LOAD_BATCHES } from "@/components/markets/FeaturedMarketsClient";
import { fetchFeaturedMarkets } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  fetchFeaturedMarkets: vi.fn(),
}));

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
    vi.mocked(fetchFeaturedMarkets).mockReset();
    class NoopIntersectionObserver {
      observe() {}
      disconnect() {}
      unobserve() {}
    }
    (globalThis as any).IntersectionObserver = NoopIntersectionObserver;
  });

  afterEach(() => {
    delete (globalThis as any).IntersectionObserver;
  });

  const renderWithClient = (ui: ReactElement) => {
    const client = new QueryClient();
    return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
  };

  it("renders skeletons when no markets exist yet", () => {
    const { container } = renderWithClient(<FeaturedMarketsClient initialMarkets={[]} />);
    const skeletons = container.querySelectorAll(".animate-pulse");
    expect(skeletons.length).toBeGreaterThan(0);
  });

  it("renders a helpful notice when provided", () => {
    renderWithClient(<FeaturedMarketsClient initialMarkets={[]} emptyNotice="Type more to search" />);
    expect(screen.getByText(/type more to search/i)).toBeInTheDocument();
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
    const fetchMock = fetchFeaturedMarkets as unknown as Mock;
    fetchMock.mockResolvedValue([nextMarket]);

    renderWithClient(
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
    expect(fetchMock).toHaveBeenCalledWith(expect.any(Number), {
      searchQuery: "sample",
      category: undefined,
      offset: 1,
      status: "active",
      coalesceGroups: true,
      orderBy: "volume",
    });
  });

  it("auto-loads additional pages before showing manual button", async () => {
    let callCount = 0;
    const fetchMock = fetchFeaturedMarkets as unknown as Mock<number>;
    fetchMock.mockImplementation(() => {
      callCount += 1;
      return Promise.resolve([
        {
          eventId: `evt-auto-${callCount}`,
          title: `Auto Market ${callCount}`,
          category: "Auto",
          outcomes: [],
          outcomePrices: [],
        },
      ]);
    });

    class InstantIntersectionObserver {
      callback: IntersectionObserverCallback;
      constructor(callback: IntersectionObserverCallback) {
        this.callback = callback;
        // trigger immediately to simulate sentinel in view
        setTimeout(() => this.callback([{ isIntersecting: true } as IntersectionObserverEntry], this as any), 0);
      }
      observe() {}
      disconnect() {}
      unobserve() {}
    }
    (globalThis as any).IntersectionObserver = InstantIntersectionObserver;

    renderWithClient(
      <FeaturedMarketsClient
        initialMarkets={[sampleMarket]}
        pageSize={1}
        maxItems={6}
      />,
    );

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });
    expect(fetchMock.mock.calls.length).toBeLessThanOrEqual(AUTO_LOAD_BATCHES);
    expect(screen.queryByRole("button", { name: /load more markets/i })).not.toBeInTheDocument();
  });

  it("preserves the order returned by the API", () => {
    const markets = [
      { eventId: "evt-a", title: "Higher 24h", volume24hUsd: 800, volume: 1_000 },
      { eventId: "evt-b", title: "Highest total", volume24hUsd: 100, volume: 5_000 },
    ];

    const { container } = renderWithClient(
      <FeaturedMarketsClient initialMarkets={markets} sortBy="totalVolume" />,
    );

    const titles = Array.from(container.querySelectorAll("h3")).map((node) => node.textContent ?? "");
    expect(titles[0]).toContain("Higher 24h");
  });
});
