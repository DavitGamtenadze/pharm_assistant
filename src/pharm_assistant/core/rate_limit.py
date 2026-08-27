"""In-process sliding-window rate limiting."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException, Request, status


class RateLimiter:
    """Bound request bursts without introducing an external dependency."""

    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = max(1, limit)
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            bucket = self._hits[key]
            while bucket and now - bucket[0] > self.window_seconds:
                bucket.popleft()
            if len(bucket) >= self.limit:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many requests. Wait a moment and try again.",
                    headers={"Retry-After": str(int(self.window_seconds))},
                )
            bucket.append(now)


def client_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def require_rate_limit(limiter: RateLimiter):
    def dependency(request: Request) -> None:
        limiter.check(client_ip(request))

    return dependency
