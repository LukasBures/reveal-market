import React from "react";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";
import HomePage from "@/app/page";

vi.mock("@/lib/api", () => ({
  fetchFeaturedMarkets: vi.fn().mockResolvedValue([
    {
      eventId: "evt-1",
      title: "Sample market",
      category: "Politics",
      outcomes: ["Yes", "No"],
      outcomePrices: [0.7, 0.3],
    },
  ]),
}));

describe("HomePage", () => {
  it("renders filters and market cards", async () => {
    const ui = await HomePage();
    render(ui);

    expect(
      screen.getByRole("heading", {
        name: /Live markets across every narrative/i,
      })
    ).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/search markets/i)).toBeInTheDocument();
    expect(screen.getByText("Sample market")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /browse documentation/i })
    ).toHaveAttribute("href", "/docs");
  });
});
