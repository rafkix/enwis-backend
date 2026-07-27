import logging
import time

from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger("app.middleware")


class RequestLoggerMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        path = scope.get("path", "")
        start = time.time()
        logger.info(f"\u2192  {method:7s} {path}")

        status_code = 0

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        await self.app(scope, receive, send_wrapper)
        duration = (time.time() - start) * 1000
        logger.info(f"\u2190  {method:7s} {path} | {status_code} | {duration:.1f}ms")


class SecurityHeadersMiddleware:
    """Adds standard security-related response headers that were missing
    entirely (no CSP, no X-Frame-Options, no HSTS, etc.) — flagged by an
    external security check. This is api.enwis.uz, so the policy is
    intentionally locked down (default-src 'none') since this origin
    only ever returns JSON / static files, never renders its own HTML
    pages for end users. The interactive docs (/api/v1/docs, /api/v1/redoc,
    DEBUG-only) load their own inline scripts/styles from a CDN, so CSP is
    relaxed only on those two paths — everything else stays locked down.
    """

    _DOCS_PATHS = {"/api/v1/docs", "/api/v1/redoc"}

    _LOCKED_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    _DOCS_CSP = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "img-src 'self' data: https://fastapi.tiangolo.com; "
        "frame-ancestors 'none'; base-uri 'none'"
    )

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        csp = self._DOCS_CSP if path in self._DOCS_PATHS else self._LOCKED_CSP

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.extend(
                    [
                        (b"content-security-policy", csp.encode()),
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"strict-origin-when-cross-origin"),
                        (
                            b"permissions-policy",
                            b"geolocation=(), microphone=(), camera=()",
                        ),
                        (
                            b"strict-transport-security",
                            b"max-age=63072000; includeSubDomains; preload",
                        ),
                    ]
                )
            await send(message)

        await self.app(scope, receive, send_wrapper)
