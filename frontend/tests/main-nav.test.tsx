import React from "react";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { MainNav } from "@/components/layout/MainNav";
import { AppProviders } from "@/components/providers/AppProviders";

const pathnameState = vi.hoisted(() => ({ value: "/" }));

vi.mock("next/navigation", () => ({
  usePathname: () => pathnameState.value,
}));

function renderWithProviders(ui: React.ReactElement) {
  return render(ui, {
    wrapper: ({ children }) => <AppProviders>{children}</AppProviders>,
  });
}

describe("MainNav", () => {
  it("links the brand to the homepage", () => {
    pathnameState.value = "/";
    renderWithProviders(<MainNav />);
    expect(screen.getByRole("link", { name: /reveal market/i })).toHaveAttribute("href", "/");
  });

  it("renders navigation links and the connect CTA", () => {
    pathnameState.value = "/";
    renderWithProviders(<MainNav />);
    expect(screen.getByRole("button", { name: /connect wallet/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /search/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /proofs/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /dashboard/i })).toBeInTheDocument();
    expect(screen.getByRole("navigation")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /open navigation/i })).toBeInTheDocument();
  });

  it("marks proofs as wallet optional", () => {
    pathnameState.value = "/proofs";
    renderWithProviders(<MainNav />);
    expect(screen.queryByRole("button", { name: /connect wallet/i })).not.toBeInTheDocument();
    expect(screen.getByText(/wallet optional/i)).toBeInTheDocument();
  });
});
