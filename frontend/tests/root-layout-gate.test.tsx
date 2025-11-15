import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, beforeEach, afterEach, it, expect, vi } from "vitest";

import RootLayout from "@/app/layout";

const mockCookies = vi.fn();

vi.mock("next/headers", () => ({
  cookies: () => mockCookies(),
}));

vi.mock("@/components/providers/AppProviders", () => ({
  AppProviders: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock("@/components/providers/HeartbeatClient", () => ({
  HeartbeatClient: () => <div data-testid="heartbeat" />,
}));

vi.mock("@/components/layout/MainNav", () => ({
  MainNav: () => <div data-testid="main-nav">Nav</div>,
}));

vi.mock("@/components/layout/Footer", () => ({
  Footer: () => <div data-testid="footer">Footer</div>,
}));

const originalEnv = process.env.LANDING_ACCESS_CODE;

describe("RootLayout gate", () => {
  beforeEach(() => {
    mockCookies.mockReset();
  });

  afterEach(() => {
    if (originalEnv === undefined) {
      delete process.env.LANDING_ACCESS_CODE;
    } else {
      process.env.LANDING_ACCESS_CODE = originalEnv;
    }
  });

  it("renders the app shell when the gate is disabled", async () => {
    process.env.LANDING_ACCESS_CODE = "";
    mockCookies.mockReturnValue({ get: vi.fn() });

    const ui = await RootLayout({ children: <>Child content</> });
    render(ui);

    expect(screen.getByTestId("main-nav")).toBeInTheDocument();
    expect(screen.getByText("Child content")).toBeInTheDocument();
    expect(screen.queryByText(/Private beta/i)).not.toBeInTheDocument();
  });

  it("shows the landing gate when access is required and no cookie is set", async () => {
    process.env.LANDING_ACCESS_CODE = "rm125";
    mockCookies.mockReturnValue({ get: vi.fn().mockReturnValue(undefined) });

    const ui = await RootLayout({ children: <>Hidden content</> });
    render(ui);

    expect(screen.getByText(/Private beta/i)).toBeInTheDocument();
    expect(screen.queryByTestId("main-nav")).not.toBeInTheDocument();
    expect(screen.queryByText("Hidden content")).not.toBeInTheDocument();
  });

  it("allows the main app through when the cookie exists", async () => {
    process.env.LANDING_ACCESS_CODE = "rm125";
    mockCookies.mockReturnValue({ get: vi.fn().mockReturnValue({ value: "granted" }) });

    const ui = await RootLayout({ children: <>Welcome in</> });
    render(ui);

    expect(screen.getByTestId("main-nav")).toBeInTheDocument();
    expect(screen.getByText("Welcome in")).toBeInTheDocument();
    expect(screen.queryByText(/Private beta/i)).not.toBeInTheDocument();
  });
});
