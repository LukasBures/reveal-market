import { within } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import RootLayout from "@/app/layout";

const mainNavSpy = vi.fn();
const cookieStoreMock = { get: vi.fn() };

vi.mock("@/components/layout/MainNav", () => ({
  MainNav: (props: unknown) => {
    mainNavSpy(props);
    return null;
  },
}));

vi.mock("next/headers", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("next/headers");
  return {
    ...actual,
    cookies: () => Promise.resolve(cookieStoreMock),
  };
});

const renderLayout = async (children: ReactNode) => {
  const ui = await RootLayout({ children });
  const markup = renderToStaticMarkup(ui);
  const doc = new DOMParser().parseFromString(markup, "text/html");
  return within(doc.body);
};

describe("RootLayout", () => {
  beforeEach(() => {
    cookieStoreMock.get.mockReset();
    mainNavSpy.mockClear();
    process.env.LANDING_ACCESS_CODE = "secret-code";
  });

  afterEach(() => {
    delete process.env.LANDING_ACCESS_CODE;
  });

  it("renders children with global scaffolding", async () => {
    const view = await renderLayout(<>Child content</>);

    expect(view.getByText("Child content")).toBeInTheDocument();
  });

  it("passes denied access to MainNav when the gate is configured and cookie missing", async () => {
    cookieStoreMock.get.mockReturnValue(undefined);

    await renderLayout(<div />);

    expect(mainNavSpy).toHaveBeenCalledWith(expect.objectContaining({ initialHasAccess: false }));
  });

  it("passes granted access to MainNav when the gate cookie is present", async () => {
    cookieStoreMock.get.mockReturnValue({ value: "granted" });

    await renderLayout(<div />);

    expect(mainNavSpy).toHaveBeenCalledWith(expect.objectContaining({ initialHasAccess: true }));
  });

  it("defaults to access granted when the gate is disabled", async () => {
    delete process.env.LANDING_ACCESS_CODE;
    cookieStoreMock.get.mockReturnValue(undefined);

    await renderLayout(<div />);

    expect(mainNavSpy).toHaveBeenCalledWith(expect.objectContaining({ initialHasAccess: true }));
  });
});
