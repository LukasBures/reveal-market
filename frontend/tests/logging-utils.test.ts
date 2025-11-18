import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("frontend logging utilities", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    vi.unstubAllGlobals();
    delete (globalThis as any).window;
    delete process.env.NEXT_PUBLIC_FRONTEND_LOG_ENDPOINT;
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    delete (globalThis as any).window;
    delete process.env.NEXT_PUBLIC_FRONTEND_LOG_ENDPOINT;
  });

  it("sends browser warnings to the remote logging endpoint", async () => {
    (globalThis as any).window = {} as Window & typeof globalThis;
    process.env.NEXT_PUBLIC_FRONTEND_LOG_ENDPOINT = "https://logs.reveal.test";
    const fetchMock = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("fetch", fetchMock);
    const consoleWarn = vi.spyOn(console, "warn").mockImplementation(() => {});

    const { logger } = await import("@/lib/logging");
    logger.clientWarn("ui.warn", { component: "HeroCTA" });

    expect(consoleWarn).toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledWith(
      "https://logs.reveal.test",
      expect.objectContaining({
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          level: "warn",
          message: "ui.warn",
          meta: { component: "HeroCTA" },
        }),
        keepalive: true,
      }),
    );

    consoleWarn.mockRestore();
  });

  it("starts a single heartbeat interval on the server", async () => {
    vi.useFakeTimers();
    const consoleInfo = vi.spyOn(console, "info").mockImplementation(() => {});
    const setIntervalSpy = vi.spyOn(global, "setInterval");

    const { ensureHeartbeat } = await import("@/lib/logging");
    ensureHeartbeat(25);
    ensureHeartbeat(25);

    expect(setIntervalSpy).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(25);

    const heartbeatLine = consoleInfo.mock.calls.at(-1)?.[0] as string;
    expect(heartbeatLine).toContain("heartbeat");
    expect(heartbeatLine).toContain('"heartbeatIntervalMs":25');

    setIntervalSpy.mockRestore();
    consoleInfo.mockRestore();
  });
});
