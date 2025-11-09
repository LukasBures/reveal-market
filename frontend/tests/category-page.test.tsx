import { render, screen } from "@testing-library/react";
import { Suspense } from "react";
import { describe, expect, it, vi } from "vitest";
import CategoryPage from "@/app/categories/[category]/page";
import { fetchFeaturedMarkets } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  fetchFeaturedMarkets: vi.fn().mockResolvedValue([
    {
      eventId: "evt-category",
      title: "Category Market",
      category: "AI & Tech",
      outcomes: [],
      outcomePrices: [],
    },
  ]),
}));

vi.mock("next/navigation", async (importOriginal) => {
  const actual = await importOriginal<any>();
  return {
    ...actual,
    notFound: vi.fn(() => {
      throw new Error("NOT_FOUND");
    }),
  };
});

describe("CategoryPage", () => {
  it("renders markets with Suspense boundary", async () => {
    const element = await CategoryPage({ params: Promise.resolve({ category: "ai-tech" }) });
    render(<Suspense fallback={<div>loading</div>}>{element}</Suspense>);
    expect(fetchFeaturedMarkets).toHaveBeenCalledWith(expect.any(Number), expect.objectContaining({ category: "ai-tech" }));
    expect(await screen.findByText("Category Market")).toBeInTheDocument();
  });

  it("invokes notFound for invalid slug", async () => {
    await expect(CategoryPage({ params: Promise.resolve({ category: "unknown" }) })).rejects.toThrow("NOT_FOUND");
  });
});
