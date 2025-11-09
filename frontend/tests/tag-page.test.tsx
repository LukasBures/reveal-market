import { render, screen } from "@testing-library/react";
import { Suspense } from "react";
import { describe, expect, it, vi } from "vitest";
import TagPage from "@/app/tags/[tag]/page";
import { fetchFeaturedMarkets } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  fetchFeaturedMarkets: vi.fn().mockResolvedValue([
    {
      eventId: "evt-tag",
      title: "Tagged Market",
      category: "Politics",
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

describe("TagPage", () => {
  it("renders tagged markets", async () => {
    const element = await TagPage({ params: Promise.resolve({ tag: "btc-halving" }) });
    render(<Suspense fallback={<div>loading</div>}>{element}</Suspense>);
    expect(fetchFeaturedMarkets).toHaveBeenCalledWith(expect.any(Number), expect.objectContaining({ tag: "btc-halving" }));
    expect(await screen.findByText("Tagged Market")).toBeInTheDocument();
  });

  it("invokes notFound for invalid slug", async () => {
    await expect(TagPage({ params: Promise.resolve({ tag: "unknown" }) })).rejects.toThrow("NOT_FOUND");
  });
});
