import { NextResponse, type NextRequest } from "next/server";

const DOCS_HOST = process.env.DOCS_HOST ?? "docs.revealmarket.xyz";

export function middleware(request: NextRequest) {
  const host = request.headers.get("host") ?? "";

  if (host === DOCS_HOST || host.startsWith(`docs.`)) {
    const url = request.nextUrl.clone();
    if (!url.pathname.startsWith("/docs")) {
      url.pathname = `/docs${url.pathname === "/" ? "" : url.pathname}`;
    }
    return NextResponse.rewrite(url);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
