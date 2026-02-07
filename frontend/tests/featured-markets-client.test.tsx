import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { FeaturedEventsClient, AUTO_LOAD_BATCHES } from "@/components/markets/FeaturedMarketsClient";
import { fetchFeaturedEvents } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  fetchFeaturedEvents: vi.fn(),
}));

const sampleEvent = {
  eventId: "evt-1",
  title: "Sample Event",
  category: "Politics",
  markets: [
    {
      eventId: "evt-1",
      title: "Sample Market",
      category: "Politics",
      tags: ["gov"],
      outcomes: ["Yes", "No"],
      outcomePrices: [0.5, 0.5],
    },
  ],
};

const sampleMarket = {
  eventId: "evt-1",
  title: "Sample Market",
  category: "Politics",
  tags: ["gov"],
  outcomes: ["Yes", "No"],
  outcomePrices: [0.5, 0.5],
};


describe("FeaturedEventsClient", () => {
  let queryClient: QueryClient | null = null;

  beforeEach(() => {
    vi.mocked(fetchFeaturedEvents).mockReset();
    delete (globalThis as any).IntersectionObserver;
  });

  afterEach(() => {
    delete (globalThis as any).IntersectionObserver;
    queryClient?.clear();
    queryClient = null;
  });

  const renderWithClient = (ui: ReactElement) => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { gcTime: 0 },
        mutations: { gcTime: 0 },
      },
    });
    return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
  };

  it("renders skeletons when no events exist yet", () => {
    renderWithClient(<FeaturedEventsClient initialMarkets={[]} />);
    expect(screen.getByText(/no markets match that yet/i)).toBeInTheDocument();
  });

  it("renders a helpful notice when provided", () => {
    renderWithClient(<FeaturedEventsClient initialMarkets={[]} emptyNotice="Type more to search" />);
    expect(screen.getByText(/type more to search/i)).toBeInTheDocument();
  });

  it("renders events and loads more on demand", async () => {
    const nextEvent = {
      eventId: "evt-2",
      title: "Second Event",
      category: "Sports",
      markets: [
        {
          eventId: "evt-2",
          title: "Second Market",
          category: "Sports",
          tags: [],
          outcomes: [],
          outcomePrices: [],
        },
      ],
    };
    const fetchMock = vi.mocked(fetchFeaturedEvents);
    fetchMock.mockResolvedValue([nextEvent]);

    renderWithClient(
      <FeaturedEventsClient
        initialMarkets={[sampleEvent]}
        pageSize={1}
        maxItems={10}
        searchQuery="sample"
        categoryFilter="Politics"
        status="settled"
        onlyActive={false}
      />,
    );

    expect(screen.getByText("Sample Event")).toBeInTheDocument();
    const button = await screen.findByRole("button", { name: /load more events/i });
    fireEvent.click(button);

    await waitFor(() => {
      expect(screen.getByText("Second Event")).toBeInTheDocument();
    });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.any(Number),
      expect.objectContaining({
        searchQuery: "sample",
        category: "politics",

        status: "settled",
        orderBy: "volume",
      }),
    );
  });

  it("keeps the load more button when a short page arrives mid-pagination", async () => {
    const fetchMock = vi.mocked(fetchFeaturedEvents);
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

    const initialBatch = Array.from({ length: 10 }, (_, idx) => ({
      ...sampleMarket,
      eventId: `evt-init-gap-${idx}`,
      title: `Initial Gap ${idx}`,
    }));

    renderWithClient(
      <FeaturedEventsClient
        initialMarkets={initialBatch}
        pageSize={10}
        maxItems={200}
      />,
    );

    const button = await screen.findByRole("button", { name: /load more events/i });
    fireEvent.click(button);

    await screen.findByText("Gap Market 0");
    const nextButton = screen.getByRole("button", { name: /load more events/i });
    expect(nextButton).toBeInTheDocument();

    fireEvent.click(nextButton);

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
    const fetchMock = vi.mocked(fetchFeaturedEvents);
    fetchMock.mockImplementation((limit = 0) => {
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

    const initialBatch = Array.from({ length: 10 }, (_, idx) => ({
      ...sampleMarket,
      eventId: `evt-init-${idx}`,
      title: `Initial Market ${idx}`,
    }));

    renderWithClient(
      <FeaturedEventsClient
        initialMarkets={initialBatch}
        pageSize={10}
        maxItems={300}
      />,
    );

    await waitFor(
      () => {
        expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(AUTO_LOAD_BATCHES);
      },
      { timeout: 3000 },
    );
    await waitFor(
      () => {
        expect(screen.getByRole("button", { name: /load more events/i })).toBeInTheDocument();
      },
      { timeout: 3000 },
    );
  }, 10000);

  it("shows a loading indicator during automatic pagination", async () => {
    let resolveFetch: (() => void) | undefined;
    const fetchMock = vi.mocked(fetchFeaturedEvents);
    fetchMock.mockImplementation((limit = 0) => {
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

    const initialBatch = Array.from({ length: 10 }, (_, idx) => ({
      ...sampleEvent,
      eventId: `evt-lazy-init-${idx}`,
      title: `Lazy Initial ${idx}`,
    }));

    renderWithClient(
      <FeaturedEventsClient
        initialMarkets={initialBatch}
        pageSize={10}
        maxItems={120}
      />,
    );

    const initialCalls = fetchMock.mock.calls.length;
    act(() => {
      observerCallback?.([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver);
    });

    await waitFor(() => {
      expect(fetchMock.mock.calls.length).toBeGreaterThan(initialCalls);
    });

    const loading = await screen.findByTestId("auto-loading-indicator");
    expect(loading).toBeInTheDocument();

    resolveFetch?.();

    await waitFor(() => {
      expect(screen.queryByRole("status", { name: /loading/i })).not.toBeInTheDocument();
    });
  });

  it("keeps the server-provided ordering that favors total volume", () => {
    const events = [
      {
        eventId: "evt-b",
        title: "Highest total",
        markets: [{ eventId: "evt-b", title: "Highest total" }],
      },
      {
        eventId: "evt-a",
        title: "Lower total",
        markets: [{ eventId: "evt-a", title: "Lower total" }],
      },
    ];

    const { container } = renderWithClient(
      <FeaturedEventsClient initialMarkets={events} sortBy="totalVolume" />,
    );

    const titles = Array.from(container.querySelectorAll("h3")).map((node) => node.textContent ?? "");
    expect(titles[0]).toContain("Highest total");
  });
});
