import React from "react";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";
import HomePage from "@/app/page";

vi.mock("@/lib/api", () => ({
  fetchInvestorKpis: vi.fn().mockResolvedValue({
    openMarkets: 24,
    settledMarkets: 12,
    databaseLatencyMs: 42.1,
    lastUpdatedIso: "2024-11-24T10:00:00Z",
  }),
}));

describe("HomePage", () => {
  it("shows hero content, CTA links, and KPI grid", async () => {
    const ui = await HomePage();
    render(ui);

    expect(
      screen.getByRole("heading", {
        name: /ZK-settled conviction with investor-grade KPIs/i,
      })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Connect with the team/i })
    ).toHaveAttribute("href", "mailto:hello@revealmarket.xyz");
    expect(
      screen.getByRole("link", { name: /Download the investor brief/i })
    ).toHaveAttribute("href", "/docs");
    expect(
      screen.getByText(/AI-ready settlement data/i)
    ).toBeInTheDocument();
    expect(screen.getByText("24")).toBeInTheDocument();
  });
});
