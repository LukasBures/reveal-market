import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";

import { middleware } from "@/middleware";

describe("middleware route gating", () => {
  it("does not treat wallet_session as route authorization", () => {
    const request = new NextRequest("https://reveal.test/dashboard");
    const response = middleware(request);

    expect(response.headers.get("location")).toBeNull();
    expect(response.status).toBe(200);
  });

  it("still bypasses API paths", () => {
    const request = new NextRequest("https://reveal.test/api/contact");
    const response = middleware(request);

    expect(response.headers.get("location")).toBeNull();
    expect(response.status).toBe(200);
  });
});
