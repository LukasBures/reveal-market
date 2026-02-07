import React from "react";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";
import { AppProviders } from "@/components/providers/AppProviders";
import { getCookieValue } from "@/lib/cookies";

const pathnameState = vi.hoisted(() => ({ value: "/" }));

vi.mock("@/lib/env-presets", () => ({
  resolveUrlConfig: () => ({
    mode: "prod",
    siteUrl: "http://localhost:3000",
  }),
}));

vi.mock("@/lib/cookies", () => ({
  getCookieValue: vi.fn(),
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
    vi.mocked(getCookieValue).mockReset();
    vi.mocked(getCookieValue).mockReturnValue(undefined);
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
    expect(screen.getByRole("searchbox", { name: /search/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /proofs/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /dashboard/i })).toBeInTheDocument();
    expect(screen.getByRole("navigation")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /open navigation/i })).toBeInTheDocument();
  });

  it("still shows connect wallet on proofs", async () => {
    pathnameState.value = "/proofs";
    const { MainNav } = await import("@/components/layout/MainNav");
    renderWithProviders(<MainNav />);
    expect(screen.getByRole("button", { name: /connect wallet/i })).toBeInTheDocument();
  });

  it("shows the minimal landing header when gate is enabled without access", async () => {
    pathnameState.value = "/";

    const { MainNav } = await import("@/components/layout/MainNav");
    renderWithProviders(<MainNav initialHasAccess={false} gateEnabled />);

    expect(screen.getByRole("link", { name: /reveal market/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /reveal market/i })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: /request access/i })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /search/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /proofs/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /dashboard/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /connect wallet/i })).not.toBeInTheDocument();
  });

  it("renders the full nav when gate is enabled and access is granted", async () => {
    pathnameState.value = "/";

    vi.mocked(getCookieValue).mockReturnValue("granted");
    const { MainNav } = await import("@/components/layout/MainNav");
    renderWithProviders(<MainNav initialHasAccess gateEnabled />);

    expect(screen.getByRole("button", { name: /connect wallet/i })).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: /search/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /proofs/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /dashboard/i })).toBeInTheDocument();
  });
});
