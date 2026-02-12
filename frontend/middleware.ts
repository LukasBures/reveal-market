import { NextResponse, type NextRequest } from "next/server";

const PUBLIC_PATHS = [
  "/healthz",
  "/brand",
  "/icons",
  "/site.webmanifest",
  "/opengraph-image",
  "/apple-touch-icon.png",
  "/safari-pinned-tab.svg",
];

export function middleware(request: NextRequest) {
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

  return NextResponse.next({ request: { headers: requestHeaders } });
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|icons|site.webmanifest|apple-touch-icon\\.png|safari-pinned-tab\\.svg).*)"],
};
