import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MarketFilters } from "@/components/markets/MarketFilters";

const pushMock = vi.fn();
const prefetchMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: pushMock,
    prefetch: prefetchMock,
  }),
  useSearchParams: () => new URLSearchParams(),
}));

describe("MarketFilters", () => {
  beforeEach(() => {
    pushMock.mockReset();
    prefetchMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("submits search queries via the router", () => {
    render(<MarketFilters initialSearch="" />);

    const input = screen.getByPlaceholderText(/search markets/i);
    fireEvent.change(input, { target: { value: "Polymarket" } });
    fireEvent.submit(input.closest("form")!);

    expect(pushMock).toHaveBeenCalledWith("/?q=Polymarket");
  });

  it("shows autocomplete suggestions and navigates on selection", async () => {
    vi.useFakeTimers();
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

    await vi.advanceTimersByTimeAsync(250);
    await waitFor(() => {
      expect(screen.getByText("Alpha Hedge")).toBeInTheDocument();
    });

    const suggestionButton = screen.getByText("Alpha Hedge").closest("button");
    expect(suggestionButton).not.toBeNull();
    fireEvent.mouseDown(suggestionButton!);

    expect(pushMock).toHaveBeenCalledWith("/markets/evt-alpha");
    expect(fetchMock).toHaveBeenCalledWith("/markets/suggest?q=Al&limit=5", expect.any(Object));
  });
});
