import React from "react";
import { render, screen } from "@testing-library/react";
import { MainNav } from "@/components/layout/MainNav";
import { vi } from "vitest";

const mockPathname = vi.fn(() => "/about");

vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname(),
}));

describe("MainNav", () => {
  it("renders nav links and highlights active path", () => {
    render(<MainNav />);

    const marketsLink = screen.getByText("Markets");
    const aboutLink = screen.getByText("About");

    expect(marketsLink).toBeInTheDocument();
    expect(aboutLink).toHaveClass("text-brand-200");
  });

  it("includes CTA to docs", () => {
    render(<MainNav />);
    expect(screen.getByRole("link", { name: /view docs/i })).toHaveAttribute(
      "href",
      "https://docs.revealmarket.xyz"
    );
  });
});
