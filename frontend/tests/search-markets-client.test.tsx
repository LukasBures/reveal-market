import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SearchEventsClient } from "@/components/markets/SearchMarketsClient";
import { loadFeaturedEventsAction } from "@/app/actions/events";

const pushMock = vi.fn();
const replaceMock = vi.fn();
const routerMock = { push: pushMock, replace: replaceMock };
const searchParamsMock = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => routerMock,
  useSearchParams: () => searchParamsMock,
}));

vi.mock("@/app/actions/events", () => ({
  loadFeaturedEventsAction: vi.fn(),
}));

vi.mock("@/components/markets/FeaturedMarketsClient", () => ({
  FeaturedEventsClient: ({
    searchQuery,
    categoryFilter,
    status,
  }: {
    searchQuery?: string;
    categoryFilter?: string;
    status?: string;
  }) => (
    <div
      data-testid="featured-markets"
      data-search={searchQuery ?? ""}
      data-category={categoryFilter ?? ""}
      data-status={status ?? ""}
    />
  ),
}));

describe("SearchEventsClient", () => {
  beforeEach(() => {
    vi.mocked(loadFeaturedEventsAction).mockReset();
    pushMock.mockReset();
    replaceMock.mockReset();
    window.localStorage.clear();
  });

  it("applies category and status filters when searching", async () => {
    vi.mocked(loadFeaturedEventsAction).mockResolvedValue({ data: [] });

    render(<SearchEventsClient initialResults={[]} />);

    const input = screen.getByPlaceholderText(/search by keyword/i);
    fireEvent.change(input, { target: { value: "Bitcoin" } });
    fireEvent.submit(input.closest("form")!);

    await waitFor(() => {
      expect(loadFeaturedEventsAction).toHaveBeenCalledTimes(1);
    });

    expect(loadFeaturedEventsAction).toHaveBeenLastCalledWith(
      expect.any(Number),
      expect.objectContaining({
        searchQuery: "Bitcoin",
        status: "any",
        category: undefined,
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Crypto" }));

    await waitFor(() => {
      expect(loadFeaturedEventsAction).toHaveBeenCalledTimes(2);
    });

    expect(loadFeaturedEventsAction).toHaveBeenLastCalledWith(
      expect.any(Number),
      expect.objectContaining({
        searchQuery: "Bitcoin",
        status: "any",
        category: "Crypto",
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Locked" }));

    await waitFor(() => {
      expect(loadFeaturedEventsAction).toHaveBeenCalledTimes(3);
    });

    expect(loadFeaturedEventsAction).toHaveBeenLastCalledWith(
      expect.any(Number),
      expect.objectContaining({
        searchQuery: "Bitcoin",
        status: "locked",
        category: "Crypto",
      }),
    );
  });

  it("stores recent searches and re-runs them", async () => {
    vi.mocked(loadFeaturedEventsAction).mockResolvedValue({ data: [] });

    render(<SearchEventsClient initialResults={[]} />);

    const input = screen.getByPlaceholderText(/search by keyword/i);
    fireEvent.change(input, { target: { value: "Solana" } });
    fireEvent.submit(input.closest("form")!);

    await waitFor(() => {
      expect(loadFeaturedEventsAction).toHaveBeenCalledTimes(1);
    });

    const stored = JSON.parse(window.localStorage.getItem("rm_recent_searches") ?? "[]");
    expect(stored[0]).toBe("Solana");

    const recentButton = await screen.findByRole("button", { name: "Solana" });
    fireEvent.click(recentButton);

    await waitFor(() => {
      expect(loadFeaturedEventsAction).toHaveBeenCalledTimes(1);
    });
  });

  it("focuses the search input with keyboard shortcuts", () => {
    render(<SearchEventsClient initialResults={[]} />);

    const input = screen.getByPlaceholderText(/search by keyword/i);
    expect(input).not.toHaveFocus();

    fireEvent.keyDown(document.body, { key: "/" });
    expect(input).toHaveFocus();
  });
});
