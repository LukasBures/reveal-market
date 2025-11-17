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

  it("shows only the Connect Wallet CTAs (no docs link)", () => {
    renderWithProviders(<MainNav />);
    expect(screen.getByRole("button", { name: /connect wallet/i })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /docs/i })).not.toBeInTheDocument();
  });

  it("renders the navigation bar and menu toggle", () => {
    renderWithProviders(<MainNav />);
    expect(screen.getByRole("navigation")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /menu/i })).toBeInTheDocument();
  });
});
