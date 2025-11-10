import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    expect(fetchMock).toHaveBeenCalledWith("/markets/suggest?q=Al&limit=5", expect.any(Object));
  });

  it("falls back to the markets endpoint when suggestions are empty", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => [] })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => [
          {
            event_id: "evt-beta",
            title: "Beta Hedge",
            category: "Crypto",
          },
        ],
      });
    vi.stubGlobal("fetch", fetchMock);

    render(<MarketFilters />);

    const input = screen.getByPlaceholderText(/search markets/i);
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "Bi" } });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByText("Beta Hedge")).toBeInTheDocument());

    const suggestionButton = screen.getByText("Beta Hedge").closest("button");
    fireEvent.mouseDown(suggestionButton!);

    expect(pushMock).toHaveBeenCalledWith("/markets/evt-beta");
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/markets?limit=5&search=Bi",
      expect.any(Object),
    );
  });
});
