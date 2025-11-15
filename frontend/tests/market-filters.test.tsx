import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MarketFilters } from "@/components/markets/MarketFilters";

const pushMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: pushMock,
    prefetch: vi.fn(),
  }),
  useSearchParams: () => new URLSearchParams(),
}));

describe("MarketFilters", () => {
  const runDebounce = async () => {
    await act(async () => {
      vi.runOnlyPendingTimers();
      await Promise.resolve();
    });
  };

  beforeEach(() => {
    pushMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("submits search queries via the router", () => {
    render(<MarketFilters initialSearch="" />);

    const input = screen.getByPlaceholderText(/search markets/i);
    fireEvent.change(input, { target: { value: "Polymarket" } });
    fireEvent.submit(input.closest("form")!);

    expect(pushMock).toHaveBeenCalledWith("/?q=Polymarket");
  });

  it("shows autocomplete suggestions and navigates on selection", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [
        {
          event_id: "evt-alpha",
          title: "Alpha Hedge",
          category: "Politics",
          tags: ["gov-shutdown"],
        },
      ],
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MarketFilters />);

    const input = screen.getByPlaceholderText(/search markets/i);
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "Al" } });

    await waitFor(() => expect(screen.getByText("Alpha Hedge")).toBeInTheDocument());

    const suggestionButton = screen.getByText("Alpha Hedge").closest("button");
    expect(suggestionButton).not.toBeNull();
    fireEvent.mouseDown(suggestionButton!);

    expect(pushMock).toHaveBeenCalledWith("/markets/evt-alpha");
    expect(fetchMock).toHaveBeenCalledWith("/api/markets/suggest?limit=5&q=Al", expect.objectContaining({ signal: expect.any(AbortSignal) }));
  });

  it("caches successful suggestion queries", async () => {
    vi.useFakeTimers();
    try {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => [
          {
            event_id: "evt-cache",
            title: "Cache Hit Market",
            category: "Politics",
          },
        ],
      });
      vi.stubGlobal("fetch", fetchMock);

      render(<MarketFilters />);

      const input = screen.getByPlaceholderText(/search markets/i);
      fireEvent.focus(input);
      fireEvent.change(input, { target: { value: "Cache" } });

      await runDebounce();
      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
      await waitFor(() => expect(screen.getByText("Cache Hit Market")).toBeInTheDocument());

      fetchMock.mockClear();
      fireEvent.change(input, { target: { value: "Cache " } });
      await runDebounce();
      await waitFor(() => expect(fetchMock).not.toHaveBeenCalled());
    } finally {
      vi.useRealTimers();
    }
  });
});
