import React from "react";
import { render, screen } from "@testing-library/react";
import HomePage from "@/app/page";

describe("HomePage", () => {
  it("shows hero content and CTA links", () => {
    render(<HomePage />);

    expect(
      screen.getByRole("heading", {
        name: /Private conviction\. Public settlement\./i,
      })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Book an investor briefing/i })
    ).toHaveAttribute("href", "mailto:hello@revealmarket.xyz");
    expect(
      screen.getByRole("link", { name: /Explore the investor docs/i })
    ).toHaveAttribute("href", "/docs");
    expect(screen.getByText(/AI-ready prediction data/i)).toBeInTheDocument();
    expect(screen.getByText(/120\+/i)).toBeInTheDocument();
  });
});
