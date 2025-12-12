import { describe, beforeEach, afterEach, it, expect, vi } from "vitest";

import {
  LANDING_ACCESS_COOKIE_MAX_AGE_SECONDS,
  LANDING_ACCESS_COOKIE_NAME,
} from "@/lib/access-gate";

const setCookieMock = vi.fn();
const mockCookies = vi.fn();
const redirectMock = vi.fn();

vi.mock("next/headers", () => ({
  cookies: () => mockCookies(),
}));

vi.mock("next/navigation", () => ({
  redirect: redirectMock,
}));

async function importActionModule() {
  vi.resetModules();
  return import("@/app/actions/landing-access");
}

describe("requestLandingAccessAction", () => {
  const originalEnv = process.env.LANDING_ACCESS_CODE;
  const originalEnvName = process.env.RM_ENVIRONMENT;

  beforeEach(() => {
    mockCookies.mockReturnValue({
      get: vi.fn(),
      set: setCookieMock,
    });
    process.env.RM_ENVIRONMENT = "production";
  });

  afterEach(() => {
    vi.clearAllMocks();
    if (originalEnvName === undefined) {
      delete process.env.RM_ENVIRONMENT;
    } else {
      process.env.RM_ENVIRONMENT = originalEnvName;
    }
    if (originalEnv === undefined) {
      delete process.env.LANDING_ACCESS_CODE;
    } else {
      process.env.LANDING_ACCESS_CODE = originalEnv;
    }
  });

  it("returns an error when the access code is not configured", async () => {
    delete process.env.LANDING_ACCESS_CODE;
    const { requestLandingAccessAction } = await importActionModule();
    const formData = new FormData();
    formData.set("accessCode", "anything");

    const result = await requestLandingAccessAction({}, formData);

    expect(result).toEqual({ error: "Access code is not configured." });
    expect(setCookieMock).not.toHaveBeenCalled();
    expect(redirectMock).not.toHaveBeenCalled();
  });

  it("rejects an invalid code", async () => {
    process.env.LANDING_ACCESS_CODE = "rm125";
    const { requestLandingAccessAction } = await importActionModule();
    const formData = new FormData();
    formData.set("accessCode", "wrong");

    const result = await requestLandingAccessAction({}, formData);

    expect(result).toEqual({ error: "Invalid login code." });
    expect(setCookieMock).not.toHaveBeenCalled();
    expect(redirectMock).not.toHaveBeenCalled();
  });

  it("sets the cookie and returns success when the code matches", async () => {
    process.env.LANDING_ACCESS_CODE = "rm125";
    const { requestLandingAccessAction } = await importActionModule();
    const formData = new FormData();
    formData.set("accessCode", "rm125");

    const result = await requestLandingAccessAction({}, formData);

    expect(result).toEqual({ success: true });
    expect(setCookieMock).toHaveBeenCalledWith({
      name: LANDING_ACCESS_COOKIE_NAME,
      value: "granted",
      httpOnly: true,
      secure: true,
      sameSite: "lax",
      path: "/",
      maxAge: LANDING_ACCESS_COOKIE_MAX_AGE_SECONDS,
    });
    expect(redirectMock).not.toHaveBeenCalled();
  });
});
