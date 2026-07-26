import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


class RateLimiter:
    def __init__(self, max_calls: int, period_seconds: int):
        self.max_calls = max_calls
        self.period = period_seconds
        self._calls: dict[str, deque] = defaultdict(deque)

    def _get_key(self, request: Request) -> str:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def __call__(self, request: Request) -> None:
        key = self._get_key(request)
        now = time.monotonic()
        window_start = now - self.period
        q = self._calls[key]

        while q and q[0] < window_start:
            q.popleft()

        if len(q) >= self.max_calls:
            retry_after = int(self.period - (now - q[0])) + 1
            raise HTTPException(
                status_code=429,
                detail=f"Juda ko'p so'rov. {retry_after} soniyadan keyin qayta urinib ko'ring.",
                headers={"Retry-After": str(retry_after)},
            )
        q.append(now)


login_limiter = RateLimiter(max_calls=10, period_seconds=60)
forgot_password_limiter = RateLimiter(max_calls=3, period_seconds=60)
sms_limiter = RateLimiter(max_calls=3, period_seconds=60)
