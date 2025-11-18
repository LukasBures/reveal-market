import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const loggerMock = {
  info: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
  debug: vi.fn(),
};

vi.mock("@/lib/logging", () => ({
  logger: loggerMock,
}));

const originalEnv = { ...process.env };

function resetEnv() {
  for (const key of Object.keys(process.env)) {
    if (!(key in originalEnv)) {
      delete process.env[key];
    }
  }
  for (const [key, value] of Object.entries(originalEnv)) {
    if (typeof value === "undefined") {
      delete process.env[key];
    } else {
      process.env[key] = value;
    }
  }
}

describe("serverEnv", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    resetEnv();
  });

  afterEach(() => {
    resetEnv();
  });

  it("prefers configured API base URLs", async () => {
    process.env.RM_API_BASE_URL = "https://api.reveal.test";
    const module = await import("@/lib/serverEnv");
    expect(module.getServerEnv().apiBaseUrl).toBe("https://api.reveal.test");
  });

  it("falls back to offline URL in non-production environments", async () => {
    delete process.env.RM_API_BASE_URL;
    process.env.NODE_ENV = "test";
    const module = await import("@/lib/serverEnv");
    expect(module.getServerEnv().apiBaseUrl).toBe("http://localhost:8000");
    expect(loggerMock.info).toHaveBeenCalledWith("serverEnv:offline_fallback", { fallback: "http://localhost:8000" });
  });

  it("throws when a malformed URL is configured in production", async () => {
    process.env.RM_API_BASE_URL = "not a valid url";
    process.env.NODE_ENV = "production";

    await expect(import("@/lib/serverEnv")).rejects.toThrow(/invalid/i);
  });
});
