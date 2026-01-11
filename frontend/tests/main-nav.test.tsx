import React from "react";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";
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
  beforeEach(() => {
    // reset pathname before each test
    pathnameState.value = "/";
  });

  afterEach(() => {
    pathnameState.value = "/";
  });

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

  it("still shows connect wallet on proofs", () => {
    pathnameState.value = "/proofs";
    renderWithProviders(<MainNav />);
    expect(screen.getByRole("button", { name: /connect wallet/i })).toBeInTheDocument();
  });

  it("shows the minimal landing header when gate is enabled without access", () => {
    pathnameState.value = "/";

    renderWithProviders(<MainNav initialHasAccess={false} gateEnabled />);

    expect(screen.getByRole("link", { name: /reveal market/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /reveal market/i })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: /request access/i })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /search/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /proofs/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /dashboard/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /connect wallet/i })).not.toBeInTheDocument();
  });

  it("renders the full nav when gate is enabled and access is granted", () => {
    pathnameState.value = "/";

    renderWithProviders(<MainNav initialHasAccess gateEnabled />);

    expect(screen.getByRole("button", { name: /connect wallet/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /search/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /proofs/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /dashboard/i })).toBeInTheDocument();
  });
});
