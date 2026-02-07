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
vi.mock("@/components/markets/FeaturedMarketsSection", () => ({
  FeaturedEventsSection: (props: { categoryFilter?: string }) => {
    featuredEventsSpy(props);
    return <div data-testid="featured">Featured Events</div>;
  },
  FeaturedEventsSkeleton: () => <div data-testid="featured-skeleton">Loading...</div>,
}));

describe("HomePage", () => {
  it("renders filters and market cards", async () => {
    const ui = await HomePage({ searchParams: Promise.resolve({}) });
    render(ui);

    expect(screen.getByTestId("featured")).toBeInTheDocument();
  });

  it("renders homepage category bar links", async () => {
    const ui = await HomePage({ searchParams: Promise.resolve({}) });
    render(ui);

    expect(screen.getByRole("link", { name: "All" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Crypto" })).toHaveAttribute("href", "/?category=crypto");
    expect(screen.getByRole("link", { name: "Finance" })).toHaveAttribute("href", "/?category=finance");
    expect(screen.getByRole("link", { name: "Sports" })).toHaveAttribute("href", "/?category=sports");
    expect(screen.getByRole("link", { name: "Politics" })).toHaveAttribute("href", "/?category=politics");
    expect(screen.getByRole("link", { name: "Geopolitics" })).toHaveAttribute("href", "/?category=geopolitics");
    expect(screen.getByRole("link", { name: "Tech" })).toHaveAttribute("href", "/?category=ai-tech");
    expect(screen.getByRole("link", { name: "Elections" })).toHaveAttribute("href", "/?category=elections");
    expect(screen.getByRole("link", { name: "Trending" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Volume" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Newest" })).toBeInTheDocument();
  });

  it("passes category filter through to featured events", async () => {
    featuredEventsSpy.mockClear();
    const ui = await HomePage({ searchParams: Promise.resolve({ category: "sports" }) });
    render(ui);

    expect(screen.getByTestId("featured")).toBeInTheDocument();
    expect(featuredEventsSpy).toHaveBeenCalledWith(expect.objectContaining({ categoryFilter: "Sports" }));
  });
});
