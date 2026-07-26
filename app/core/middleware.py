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
