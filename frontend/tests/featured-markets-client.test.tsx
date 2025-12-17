import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
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
    delete (globalThis as any).IntersectionObserver;
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

  it("keeps the load more button when a short page arrives mid-pagination", async () => {
    const fetchMock = fetchFeaturedMarkets as unknown as Mock;
    fetchMock
      .mockResolvedValueOnce(
        Array.from({ length: 10 }, (_, idx) => ({
          eventId: `evt-gap-${idx}`,
          title: `Gap Market ${idx}`,
          category: "Sports",
          outcomes: [],
          outcomePrices: [],
        })),
      )
      .mockResolvedValueOnce(
        Array.from({ length: 5 }, (_, idx) => ({
          eventId: `evt-gap-next-${idx}`,
          title: `Gap Market Next ${idx}`,
          category: "Politics",
          outcomes: [],
          outcomePrices: [],
        })),
      );

    const initialBatch = Array.from({ length: 30 }, (_, idx) => ({
      ...sampleMarket,
      eventId: `evt-init-gap-${idx}`,
      title: `Initial Gap ${idx}`,
    }));

    renderWithClient(
      <FeaturedMarketsClient
        initialMarkets={initialBatch}
        pageSize={30}
        maxItems={200}
      />,
    );

    const button = screen.getByRole("button", { name: /load more markets/i });
    fireEvent.click(button);

    await screen.findByText("Gap Market 0");
    expect(screen.getByRole("button", { name: /load more markets/i })).toBeInTheDocument();

    fireEvent.click(button);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenNthCalledWith(
        2,
        expect.any(Number),
        expect.objectContaining({ offset: initialBatch.length + 10 }),
      );
    });
  });

  it("auto-loads batches then surfaces the manual button after the cap", async () => {
    let callCount = 0;
    const fetchMock = fetchFeaturedMarkets as unknown as Mock<number>;
    fetchMock.mockImplementation((limit: number) => {
      callCount += 1;
      return Promise.resolve(
        Array.from({ length: limit }, (_, idx) => ({
          eventId: `evt-auto-${callCount}-${idx}`,
          title: `Auto Market ${callCount}-${idx}`,
          category: "Auto",
          outcomes: [],
          outcomePrices: [],
        })),
      );
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

    const initialBatch = Array.from({ length: 30 }, (_, idx) => ({
      ...sampleMarket,
      eventId: `evt-init-${idx}`,
      title: `Initial Market ${idx}`,
    }));

    renderWithClient(
      <FeaturedMarketsClient
        initialMarkets={initialBatch}
        pageSize={30}
        maxItems={300}
      />,
    );

    await waitFor(() => {
      expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(AUTO_LOAD_BATCHES);
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /load more markets/i })).toBeInTheDocument();
    });
  });

  it("shows a loading indicator during automatic pagination", async () => {
    let resolveFetch: (() => void) | undefined;
    const fetchMock = fetchFeaturedMarkets as unknown as Mock<number>;
    fetchMock.mockImplementation((limit: number) => {
      return new Promise((resolve) => {
        resolveFetch = () =>
          resolve(
            Array.from({ length: limit }, (_, idx) => ({
              ...sampleMarket,
              eventId: `evt-lazy-${idx}`,
              title: `Lazy Market ${idx}`,
            })),
          );
      });
    });

    let observerCallback: IntersectionObserverCallback | null = null;
    class ManualIntersectionObserver {
      constructor(callback: IntersectionObserverCallback) {
        observerCallback = callback;
      }
      observe() {}
      disconnect() {}
      unobserve() {}
    }
    (globalThis as any).IntersectionObserver = ManualIntersectionObserver;

    const initialBatch = Array.from({ length: 30 }, (_, idx) => ({
      ...sampleMarket,
      eventId: `evt-lazy-init-${idx}`,
      title: `Lazy Initial ${idx}`,
    }));

    renderWithClient(
      <FeaturedMarketsClient
        initialMarkets={initialBatch}
        pageSize={30}
        maxItems={120}
      />,
    );

    await waitFor(() => {
      expect(observerCallback).toBeTruthy();
    });

    const initialCalls = fetchMock.mock.calls.length;
    act(() => {
      observerCallback?.([{ isIntersecting: true } as IntersectionObserverEntry], {} as any);
    });

    await waitFor(() => {
      expect(fetchMock.mock.calls.length).toBeGreaterThan(initialCalls);
      expect(
        fetchMock.mock.calls.some(([, params]) => (params as any)?.offset === initialBatch.length),
      ).toBe(true);
    });

    const loading = await screen.findByTestId("auto-loading-indicator");
    expect(loading).toBeInTheDocument();

    resolveFetch?.();

    await waitFor(() => {
      expect(screen.queryByRole("status", { name: /loading/i })).not.toBeInTheDocument();
    });
  });

  it("keeps the server-provided ordering that favors total volume", () => {
    const markets = [
      { eventId: "evt-b", title: "Highest total", volume24hUsd: 100, volume: 5_000 },
      { eventId: "evt-a", title: "Lower total", volume24hUsd: 800, volume: 1_000 },
    ];

    const { container } = renderWithClient(
      <FeaturedMarketsClient initialMarkets={markets} sortBy="totalVolume" />,
    );

    const titles = Array.from(container.querySelectorAll("h3")).map((node) => node.textContent ?? "");
    expect(titles[0]).toContain("Highest total");
  });
});
