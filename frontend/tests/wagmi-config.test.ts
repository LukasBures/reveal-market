import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const loggerMock = vi.hoisted(() => ({
  info: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
  debug: vi.fn(),
}));

vi.mock("@/lib/logging", () => ({
  logger: loggerMock,
}));

const originalEnv = { ...process.env };

const resetEnv = () => {
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
};

describe("wagmi chain defaults", () => {
  beforeEach(() => {
    vi.doUnmock("@/lib/wagmi");
    vi.doUnmock("wagmi");
    vi.resetModules();
    vi.clearAllMocks();
    resetEnv();
  });

  afterEach(() => {
    resetEnv();
  });

  it("falls back to Horizen defaults when chain config is missing", async () => {
    delete process.env.NEXT_PUBLIC_CHAIN_ID;
    delete process.env.NEXT_PUBLIC_RPC_URL;
    delete process.env.NEXT_PUBLIC_BLOCK_EXPLORER_URL;

    const module = await import("@/lib/wagmi");

    expect(module.defaultChain.id).toBe(2651420);
    expect(module.defaultChain.rpcUrls.default.http[0]).toBe("https://horizen-testnet.rpc.caldera.xyz/http");
    expect(module.defaultChain.blockExplorers?.default?.url).toBe("https://horizen-testnet.explorer.caldera.xyz");

    const warnEvents = loggerMock.warn.mock.calls.map(([event]) => event);
    expect(warnEvents).toContain("wagmi.chain_id_missing");
    expect(warnEvents).toContain("wagmi.rpc_url_missing");
    expect(warnEvents).toContain("wagmi.explorer_missing");
  });

  it("warns and overrides when an unexpected chain id is configured", async () => {
    process.env.NEXT_PUBLIC_CHAIN_ID = "1";
    process.env.NEXT_PUBLIC_CHAIN_NAME = "Wrong Chain";
    process.env.NEXT_PUBLIC_RPC_URL = "https://example-rpc.test";
    process.env.NEXT_PUBLIC_BLOCK_EXPLORER_URL = "https://example-explorer.test";

    const module = await import("@/lib/wagmi");

    expect(module.defaultChain.id).toBe(2651420);
    expect(module.defaultChain.name).toBe("Wrong Chain"); // name is kept, but chain id is enforced

    const warnEvents = loggerMock.warn.mock.calls.map(([event]) => event);
    expect(warnEvents).toContain("wagmi.chain_id_mismatch");
    expect(warnEvents).not.toContain("wagmi.rpc_url_missing");
    expect(warnEvents).not.toContain("wagmi.explorer_missing");
  });
});
