import { within } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, beforeEach, afterEach, it, expect, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import RootLayout from "@/app/layout";

const mockCookies = vi.fn();
const mockHeaders = vi.fn();

vi.mock("next/headers", () => ({
  cookies: () => mockCookies(),
  headers: () => mockHeaders(),
}));

vi.mock("@/components/providers/AppProviders", () => ({
  AppProviders: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock("@/components/landing/LandingGate", () => ({
  LandingGate: () => <div data-testid="landing-gate" />,
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

const renderLayout = async (children: ReactNode) => {
  const ui = await RootLayout({ children });
  const markup = renderToStaticMarkup(ui);
  const doc = new DOMParser().parseFromString(markup, "text/html");
  return within(doc.body);
};

describe("RootLayout gate", () => {
  beforeEach(() => {
    mockCookies.mockReset();
    mockHeaders.mockReset();
    mockHeaders.mockReturnValue({ get: vi.fn().mockReturnValue(null) });
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

    const view = await renderLayout(<>Child content</>);

    expect(view.getByTestId("main-nav")).toBeInTheDocument();
    expect(view.getByText("Child content")).toBeInTheDocument();
    expect(view.queryByText(/Private beta/i)).not.toBeInTheDocument();
  });

  it("shows the landing gate when access is required and no cookie is set", async () => {
    process.env.LANDING_ACCESS_CODE = "rm125";
    mockCookies.mockReturnValue({ get: vi.fn().mockReturnValue(undefined) });
    mockHeaders.mockReturnValue({ get: vi.fn().mockReturnValue(null) });

    const view = await renderLayout(<>Hidden content</>);

    expect(view.getByTestId("landing-gate")).toBeInTheDocument();
    expect(view.queryByTestId("main-nav")).not.toBeInTheDocument();
    expect(view.queryByText("Hidden content")).not.toBeInTheDocument();
  });

  it("allows the main app through when the cookie exists", async () => {
    process.env.LANDING_ACCESS_CODE = "rm125";
    mockCookies.mockReturnValue({ get: vi.fn().mockReturnValue({ value: "granted" }) });
    mockHeaders.mockReturnValue({ get: vi.fn().mockReturnValue(null) });

    const view = await renderLayout(<>Welcome in</>);

    expect(view.getByTestId("main-nav")).toBeInTheDocument();
    expect(view.getByText("Welcome in")).toBeInTheDocument();
    expect(view.queryByTestId("landing-gate")).not.toBeInTheDocument();
  });

  it("allows public routes through even without a cookie", async () => {
    process.env.LANDING_ACCESS_CODE = "rm125";
    mockCookies.mockReturnValue({ get: vi.fn().mockReturnValue(undefined) });
    mockHeaders.mockReturnValue({
      get: vi.fn((key: string) => (key === "x-rm-public-path" ? "1" : null)),
    });

    const view = await renderLayout(<>Public content</>);

    expect(view.getByTestId("main-nav")).toBeInTheDocument();
    expect(view.getByText("Public content")).toBeInTheDocument();
    expect(view.queryByTestId("landing-gate")).not.toBeInTheDocument();
  });
});
