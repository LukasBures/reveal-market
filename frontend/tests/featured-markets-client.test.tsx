import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import type { Mock } from "vitest";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
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
    class NoopIntersectionObserver {
      observe() {}
      disconnect() {}
      unobserve() {}
    }
    (globalThis as any).IntersectionObserver = NoopIntersectionObserver;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
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
    const fetchMock = global.fetch as unknown as Mock;
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => [nextMarket],
    });

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
    expect(fetchMock).toHaveBeenCalledWith("/markets?limit=1&offset=1&search=sample", { cache: "no-store" });
  });

  it("auto-loads additional pages before showing manual button", async () => {
    let callCount = 0;
    const fetchMock = global.fetch as unknown as Mock;
    fetchMock.mockImplementation(() => {
      callCount += 1;
      return Promise.resolve({
        ok: true,
        json: async () => [
          {
            event_id: `evt-auto-${callCount}`,
            title: `Auto Market ${callCount}`,
            category: "Auto",
          },
        ],
      });
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
      expect(fetchMock).toHaveBeenCalledTimes(3);
    });
    expect(screen.getByRole("button", { name: /load more markets/i })).toBeInTheDocument();
  });
});
