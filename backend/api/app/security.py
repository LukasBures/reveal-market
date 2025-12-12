from __future__ import annotations

from collections.abc import Mapping

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach hardened security headers to every response."""

    def __init__(
        self,
        app,
        headers: Mapping[str, str] | None = None,
        per_path_overrides: Mapping[str, Mapping[str, str]] | None = None,
    ) -> None:
        super().__init__(app)
        default_headers = {
            "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
            "X-Frame-Options": "DENY",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
            "Cross-Origin-Resource-Policy": "same-site",
            "Cross-Origin-Opener-Policy": "same-origin",
            "X-DNS-Prefetch-Control": "off",
        }
        if headers:
            default_headers.update(headers)
        self._headers = default_headers
        self._per_path_overrides = dict(per_path_overrides or {})

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        headers = dict(self._headers)
        for prefix, overrides in self._per_path_overrides.items():
            if request.url.path.startswith(prefix):
                headers.update(overrides)
        for key, value in headers.items():
            if key not in response.headers:
                response.headers[key] = value
        return response
