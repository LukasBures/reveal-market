import { NextResponse, type NextRequest } from "next/server";

// Keep the access gate consistent for all routes. If the landing access code is
// configured and the cookie is missing or invalid, redirect back to the landing
// page so users see the gate instead of partially rendering the app or failing
// route prefetches.
const LANDING_ACCESS_COOKIE_NAME = "rm_landing_access";
const PUBLIC_PATHS = [
  "/",
  "/healthz",
  "/contact",
  "/proofs",
  "/brand",
  "/icons",
  "/site.webmanifest",
  "/opengraph-image",
  "/apple-touch-icon.png",
  "/safari-pinned-tab.svg",
];

export function middleware(request: NextRequest) {
  // Skip static/assets and Next internals.
  const { pathname } = request.nextUrl;
  if (
    pathname.startsWith("/_next") ||
    pathname.startsWith("/api") ||
    pathname.startsWith("/static") ||
    pathname.startsWith("/favicon") ||
    pathname === "/apple-touch-icon.png" ||
    pathname === "/safari-pinned-tab.svg" ||
    pathname.startsWith("/robots.txt") ||
    pathname.startsWith("/sitemap.xml")
  ) {
    return NextResponse.next();
  }

  const requestHeaders = new Headers(request.headers);
  const isPublicPath = PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));
  if (isPublicPath) {
    requestHeaders.set("x-rm-public-path", "1");
  }

  const gateCode = process.env.LANDING_ACCESS_CODE?.trim();
  const hasGate = Boolean(gateCode);
  if (!hasGate) {
    return NextResponse.next({ request: { headers: requestHeaders } });
  }

  // Allow public paths through without the gate so the landing page itself loads.
  if (isPublicPath) {
    return NextResponse.next({ request: { headers: requestHeaders } });
  }

  const accessCookie = request.cookies.get(LANDING_ACCESS_COOKIE_NAME)?.value;
  if (accessCookie === "granted") {
    return NextResponse.next();
  }

  const url = request.nextUrl.clone();
  url.pathname = "/";

  // Clear any bad cookie value to avoid client-side confusion.
  const response = NextResponse.redirect(url);
  response.cookies.set({
    name: LANDING_ACCESS_COOKIE_NAME,
    value: "",
    maxAge: 0,
    path: "/",
  });
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|icons|site.webmanifest|apple-touch-icon\\.png|safari-pinned-tab\\.svg).*)"],
};
