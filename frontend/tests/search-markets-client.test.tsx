import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SearchMarketsClient } from "@/components/markets/SearchMarketsClient";
import { loadFeaturedMarketsAction } from "@/app/actions/markets";

const pushMock = vi.fn();
const replaceMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: pushMock,
    replace: replaceMock,
  }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/app/actions/markets", () => ({
  loadFeaturedMarketsAction: vi.fn(),
}));

vi.mock("@/components/markets/FeaturedMarketsClient", () => ({
  FeaturedMarketsClient: ({
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

describe("SearchMarketsClient", () => {
  beforeEach(() => {
    vi.mocked(loadFeaturedMarketsAction).mockReset();
    pushMock.mockReset();
    replaceMock.mockReset();
    window.localStorage.clear();
  });

  it("applies category and status filters when searching", async () => {
    vi.mocked(loadFeaturedMarketsAction).mockResolvedValue([]);

    render(<SearchMarketsClient initialResults={[]} />);

    const input = screen.getByPlaceholderText(/search by keyword/i);
    fireEvent.change(input, { target: { value: "Bitcoin" } });
    fireEvent.submit(input.closest("form")!);

    await waitFor(() => {
      expect(loadFeaturedMarketsAction).toHaveBeenCalledTimes(1);
    });

    expect(loadFeaturedMarketsAction).toHaveBeenLastCalledWith(
      expect.any(Number),
      expect.objectContaining({
        searchQuery: "Bitcoin",
        status: "any",
        category: undefined,
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Crypto" }));

    await waitFor(() => {
      expect(loadFeaturedMarketsAction).toHaveBeenCalledTimes(2);
    });

    expect(loadFeaturedMarketsAction).toHaveBeenLastCalledWith(
      expect.any(Number),
      expect.objectContaining({
        searchQuery: "Bitcoin",
        status: "any",
        category: "Crypto",
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Locked" }));

    await waitFor(() => {
      expect(loadFeaturedMarketsAction).toHaveBeenCalledTimes(3);
    });

    expect(loadFeaturedMarketsAction).toHaveBeenLastCalledWith(
      expect.any(Number),
      expect.objectContaining({
        searchQuery: "Bitcoin",
        status: "locked",
        category: "Crypto",
      }),
    );
  });

  it("stores recent searches and re-runs them", async () => {
    vi.mocked(loadFeaturedMarketsAction).mockResolvedValue([]);

    render(<SearchMarketsClient initialResults={[]} />);

    const input = screen.getByPlaceholderText(/search by keyword/i);
    fireEvent.change(input, { target: { value: "Solana" } });
    fireEvent.submit(input.closest("form")!);

    await waitFor(() => {
      expect(loadFeaturedMarketsAction).toHaveBeenCalledTimes(1);
    });

    const stored = JSON.parse(window.localStorage.getItem("rm_recent_searches") ?? "[]");
    expect(stored[0]).toBe("Solana");

    const recentButton = await screen.findByRole("button", { name: "Solana" });
    fireEvent.click(recentButton);

    await waitFor(() => {
      expect(loadFeaturedMarketsAction).toHaveBeenCalledTimes(2);
    });
  });

  it("focuses the search input with keyboard shortcuts", () => {
    render(<SearchMarketsClient initialResults={[]} />);

    const input = screen.getByPlaceholderText(/search by keyword/i);
    expect(input).not.toHaveFocus();

    fireEvent.keyDown(document.body, { key: "/" });
    expect(input).toHaveFocus();
  });
});
