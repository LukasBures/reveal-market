import { render, screen } from "@testing-library/react";
import { vi } from "vitest";
import HomePage from "@/app/(public)/page";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    fetchFeaturedEvents: vi.fn().mockResolvedValue([
      {
        eventId: "evt-1",
        title: "Sample event",
        category: "Politics",
        markets: [
          {
            eventId: "evt-1",
            title: "Sample market",
            category: "Politics",
            outcomes: ["Yes", "No"],
            outcomePrices: [0.7, 0.3],
          },
        ],
      },
    ]),
  };
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    prefetch: vi.fn(),
  }),
  useSearchParams: () => new URLSearchParams(),
}));

const featuredEventsSpy = vi.fn();
const MockFeaturedEventsSection = (props: { categoryFilter?: string }) => {
  featuredEventsSpy(props);
  return <div data-testid="featured">Featured Events</div>;
};
const MockFeaturedEventsSkeleton = () => <div data-testid="featured-skeleton">Loading...</div>;
const mockedFeaturedMarketsModule = {
  FeaturedEventsSection: MockFeaturedEventsSection,
  FeaturedEventsSkeleton: MockFeaturedEventsSkeleton,
};
vi.mock("@/components/markets/FeaturedMarketsSection", () => mockedFeaturedMarketsModule);

describe("HomePage", () => {
  it("renders filters and market cards", async () => {
    const ui = await HomePage({ searchParams: Promise.resolve({}) });
    render(ui);

    expect(screen.getByTestId("featured")).toBeInTheDocument();
  });

  it("passes category filter through to featured events", async () => {
    featuredEventsSpy.mockClear();
    const ui = await HomePage({ searchParams: Promise.resolve({ category: "sports" }) });
    render(ui);

    expect(screen.getByTestId("featured")).toBeInTheDocument();
    expect(featuredEventsSpy).toHaveBeenCalledWith(expect.objectContaining({ categoryFilter: "Sports" }));
  });
});
