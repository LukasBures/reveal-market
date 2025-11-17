import React from "react";
import { render, screen } from "@testing-library/react";
import { MainNav } from "@/components/layout/MainNav";
import { AppProviders } from "@/components/providers/AppProviders";

function renderWithProviders(ui: React.ReactElement) {
  return render(ui, {
    wrapper: ({ children }) => <AppProviders>{children}</AppProviders>,
  });
}

describe("MainNav", () => {
  it("links the brand to the homepage", () => {
    renderWithProviders(<MainNav />);
    expect(screen.getByRole("link", { name: /reveal market/i })).toHaveAttribute("href", "/");
  });

  it("contains Docs + Connect Wallet calls to action", () => {
    renderWithProviders(<MainNav />);
    expect(screen.getByRole("link", { name: /docs/i })).toHaveAttribute("href", "/docs");
    expect(screen.getByRole("button", { name: /connect wallet/i })).toBeInTheDocument();
  });

  it("renders a static desktop navigation bar with two actions", () => {
    renderWithProviders(<MainNav />);
    const nav = screen.getByRole("navigation");
    expect(nav).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /menu/i })).not.toBeInTheDocument();
  });
});
