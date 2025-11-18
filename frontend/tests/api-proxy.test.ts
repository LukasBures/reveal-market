import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const loggerMock = {
  info: vi.fn(),
  error: vi.fn(),
};

vi.mock("@/lib/logging", () => ({
  logger: loggerMock,
}));

vi.mock("@/lib/api", () => ({
  DEFAULT_API_BASE: "https://api.reveal.test",
}));

vi.mock("next/server", () => {
  class MockNextResponse {
    body: string;
    status: number;
    headers: Headers;

    constructor(body: string, init?: ResponseInit) {
      this.body = body;
      this.status = init?.status ?? 200;
      if (init?.headers instanceof Headers) {
        this.headers = init.headers;
      } else {
        this.headers = new Headers(init?.headers);
      }
    }

    static json(data: unknown, init?: ResponseInit) {
      const headers = init?.headers instanceof Headers ? init.headers : new Headers(init?.headers);
      if (!headers.has("content-type")) {
        headers.set("content-type", "application/json");
      }
      return new MockNextResponse(JSON.stringify(data), { ...init, headers });
    }
  }

  return { NextResponse: MockNextResponse };
});

describe("proxyApiRequest", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("forwards query params and payloads to the backend API", async () => {
    const upstreamResponse = {
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      text: vi.fn().mockResolvedValue('["ok"]'),
    };
    const fetchMock = vi.fn().mockResolvedValue(upstreamResponse);
    vi.stubGlobal("fetch", fetchMock);

    const request = new Request("https://frontend.test/api/markets?limit=5&offset=2", {
      headers: {
        accept: "application/json",
      },
    });
    const { proxyApiRequest } = await import("@/lib/server/apiProxy");
    const response = await proxyApiRequest(request, "/markets");

    expect(fetchMock).toHaveBeenCalledWith("https://api.reveal.test/markets?limit=5&offset=2", {
      headers: {
        accept: "application/json",
      },
    });
    expect(response.status).toBe(200);
    expect(response.body).toBe('["ok"]');
    expect(upstreamResponse.text).toHaveBeenCalledTimes(1);
  });

  it("returns a 502 response when the upstream fetch fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    const request = new Request("https://frontend.test/api/markets?limit=1");
    const { proxyApiRequest } = await import("@/lib/server/apiProxy");

    const response = await proxyApiRequest(request, "/markets");
    expect(response.status).toBe(502);
    expect(JSON.parse(response.body)).toEqual({ error: "upstream_unavailable" });
    expect(loggerMock.error).toHaveBeenCalledWith("apiProxy:error", expect.objectContaining({ pathname: "/markets" }));
  });
});
