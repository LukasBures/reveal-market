import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  fetchFeaturedEvents: vi.fn().mockResolvedValue({ data: [] }),
}));

import HomePage from "@/app/(public)/page";
import SearchPage from "@/app/(public)/search/page";
import { fetchFeaturedEvents } from "@/lib/api";

const fetchMock = vi.mocked(fetchFeaturedEvents);

describe("search params behavior", () => {
  it("does not search on the home page for short queries", async () => {
    fetchMock.mockClear();
    await HomePage({ searchParams: Promise.resolve({ q: "a" }) });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("search page only fetches when filters are present", async () => {
    fetchMock.mockClear();
    await SearchPage({ searchParams: Promise.resolve({ q: "a" }) });
    expect(fetchMock).not.toHaveBeenCalled();

    await SearchPage({ searchParams: Promise.resolve({ q: "ab" }) });
    expect(fetchMock).toHaveBeenCalled();
  });
});
