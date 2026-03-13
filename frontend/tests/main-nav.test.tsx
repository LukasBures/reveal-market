import React from "react";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";
import { AppProviders } from "@/components/providers/AppProviders";

const pathnameState = vi.hoisted(() => ({ value: "/" }));
const connectWalletButtonMock = vi.hoisted(() => () => <button type="button">Connect Wallet</button>);

vi.mock("@/lib/env-presets", () => ({
  resolveUrlConfig: () => ({
    mode: "prod",
    siteUrl: "http://localhost:3000",
  }),
}));

vi.mock("next/dynamic", () => ({
  __esModule: true,
  default: () => connectWalletButtonMock,
}));

vi.mock("next/navigation", () => ({
  usePathname: () => pathnameState.value,
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
  }),
  useSearchParams: () => new URLSearchParams(),
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
    process.env.RM_ENVIRONMENT = "prod";
    vi.resetModules();
  });

  afterEach(() => {
    pathnameState.value = "/";
    delete process.env.RM_ENVIRONMENT;
  });

  it("links the brand to the homepage", async () => {
    pathnameState.value = "/";
    const { MainNav } = await import("@/components/layout/MainNav");
    renderWithProviders(<MainNav />);
    expect(screen.getByRole("link", { name: /reveal market/i })).toHaveAttribute("href", "/");
  });

  it("renders navigation links and the connect CTA", async () => {
    pathnameState.value = "/";
    const { MainNav } = await import("@/components/layout/MainNav");
    renderWithProviders(<MainNav />);
    expect(screen.getByRole("button", { name: /connect wallet/i })).toBeInTheDocument();
    expect(screen.getAllByRole("searchbox", { name: /search/i }).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByRole("link", { name: /proofs/i }).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByRole("link", { name: /dashboard/i }).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByRole("navigation").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole("button", { name: /open navigation/i })).toBeInTheDocument();
  });

  it("still shows connect wallet on proofs", async () => {
    pathnameState.value = "/proofs";
    const { MainNav } = await import("@/components/layout/MainNav");
    renderWithProviders(<MainNav />);
    expect(screen.getByRole("button", { name: /connect wallet/i })).toBeInTheDocument();
  });
});
