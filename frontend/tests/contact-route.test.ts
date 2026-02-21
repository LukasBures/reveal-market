import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const loggerMock = {
  info: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
};

const getRedisClientMock = vi.fn();

vi.mock("@/lib/logging", () => ({
  logger: loggerMock,
}));

vi.mock("@/lib/redis", () => ({
  getRedisClient: getRedisClientMock,
}));

const basePayload = JSON.stringify({ name: "Alice", email: "alice@example.com", message: "hello" });

describe("contact route hardening", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    delete process.env.CONTACT_TURNSTILE_SECRET;
    delete process.env.CONTACT_DISCORD_WEBHOOK_URL;
    delete process.env.CONTACT_TRUSTED_PROXY_HOPS;
    delete process.env.CONTACT_TRUST_PROXY_HEADERS;
    delete process.env.CONTACT_TRUST_EDGE_IP_HEADERS;
    process.env.RM_ENVIRONMENT = "test";
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("does not trust X-Forwarded-For unless trusted proxy hops are configured", async () => {
    const redis = { eval: vi.fn().mockResolvedValue(1) };
    getRedisClientMock.mockReturnValue(redis);

    const { POST } = await import("@/app/api/contact/route");
    const request = new Request("https://reveal.test/api/contact", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-forwarded-for": "198.51.100.20",
        "user-agent": "vitest-agent",
      },
      body: basePayload,
    });

    const response = await POST(request);
    expect(response.status).toBe(202);
    const key = redis.eval.mock.calls[0][2] as string;
    expect(key).toBe("contact_rate:unknown");
  });

  it("uses the correct X-Forwarded-For hop when trusted proxy hops are configured", async () => {
    process.env.CONTACT_TRUSTED_PROXY_HOPS = "1";
    process.env.CONTACT_TRUST_PROXY_HEADERS = "true";
    const redis = { eval: vi.fn().mockResolvedValue(1) };
    getRedisClientMock.mockReturnValue(redis);

    const { POST } = await import("@/app/api/contact/route");
    const request = new Request("https://reveal.test/api/contact", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-forwarded-for": "203.0.113.9, 10.0.0.4",
      },
      body: basePayload,
    });

    const response = await POST(request);
    expect(response.status).toBe(202);
    expect(redis.eval).toHaveBeenCalledWith(expect.any(String), 1, "contact_rate:203.0.113.9", "600");
  });

  it("ignores edge IP headers unless explicitly trusted", async () => {
    const redis = { eval: vi.fn().mockResolvedValue(1) };
    getRedisClientMock.mockReturnValue(redis);

    const { POST } = await import("@/app/api/contact/route");
    const request = new Request("https://reveal.test/api/contact", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "cf-connecting-ip": "198.51.100.30",
      },
      body: basePayload,
    });

    const response = await POST(request);
    expect(response.status).toBe(202);
    expect(redis.eval).toHaveBeenCalledWith(expect.any(String), 1, "contact_rate:unknown", "600");
  });

  it("rejects oversized payloads before JSON parsing", async () => {
    const redis = { eval: vi.fn().mockResolvedValue(1) };
    getRedisClientMock.mockReturnValue(redis);

    const { POST } = await import("@/app/api/contact/route");
    const oversizedPayload = JSON.stringify({ message: "x".repeat(9000) });
    const request = new Request("https://reveal.test/api/contact", {
      method: "POST",
      headers: {
        "content-type": "application/json",
      },
      body: oversizedPayload,
    });

    const response = await POST(request);
    expect(response.status).toBe(413);
    expect(await response.json()).toEqual({ ok: false, error: "payload_too_large" });
  });

  it("uses atomic Redis eval instead of non-atomic INCR/EXPIRE sequence", async () => {
    const redis = {
      eval: vi.fn().mockResolvedValue(1),
      incr: vi.fn(),
      expire: vi.fn(),
    };
    getRedisClientMock.mockReturnValue(redis);

    const { POST } = await import("@/app/api/contact/route");
    const request = new Request("https://reveal.test/api/contact", {
      method: "POST",
      headers: {
        "content-type": "application/json",
      },
      body: basePayload,
    });

    const response = await POST(request);
    expect(response.status).toBe(202);
    expect(redis.eval).toHaveBeenCalledTimes(1);
    expect(redis.incr).not.toHaveBeenCalled();
    expect(redis.expire).not.toHaveBeenCalled();
  });

  it("fails closed when turnstile secret is missing in production-like environments", async () => {
    process.env.RM_ENVIRONMENT = "production";
    const redis = { eval: vi.fn().mockResolvedValue(1) };
    getRedisClientMock.mockReturnValue(redis);

    const { POST } = await import("@/app/api/contact/route");
    const request = new Request("https://reveal.test/api/contact", {
      method: "POST",
      headers: {
        "content-type": "application/json",
      },
      body: basePayload,
    });

    const response = await POST(request);
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({ ok: false, error: "verification_unavailable" });
  });
});
