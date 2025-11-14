import { NextResponse } from "next/server";
import { DEFAULT_API_BASE } from "@/lib/api";
import { logger } from "@/lib/logging";

export async function proxyApiRequest(request: Request, pathname: string) {
  const incomingUrl = new URL(request.url);
  const targetUrl = new URL(pathname, DEFAULT_API_BASE);
  incomingUrl.searchParams.forEach((value, key) => {
    targetUrl.searchParams.set(key, value);
  });

  try {
    const upstream = await fetch(targetUrl.toString(), {
      headers: {
        accept: request.headers.get("accept") ?? "application/json",
      },
    });
    const body = await upstream.text();
    const headers = new Headers();
    headers.set("content-type", upstream.headers.get("content-type") ?? "application/json");
    return new NextResponse(body, {
      status: upstream.status,
      headers,
    });
  } catch (error) {
    logger.error("apiProxy:error", { pathname, error: (error as Error).message });
    return NextResponse.json({ error: "upstream_unavailable" }, { status: 502 });
  }
}
