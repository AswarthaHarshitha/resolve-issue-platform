"""In-memory, single-process rate limiting for authentication endpoints.

This is a deliberately lightweight MVP protection, not a production-grade
distributed rate limiter - see DECISIONS.md D25. It resets on process
restart and is NOT shared across multiple worker processes or horizontally
scaled instances (each process has its own counters), so it only actually
protects a single-process deployment. A multi-instance production
deployment would need a shared store (e.g. Redis) instead - deliberately
not introduced here per the project's "no unnecessary infrastructure" rule.
"""

import time
from collections import defaultdict
from threading import Lock
from typing import Dict, List

from fastapi import HTTPException, Request, status

from app.core.config import get_settings

settings = get_settings()


class InMemoryRateLimiter:
    """Fixed-window limiter keyed by an arbitrary string (client IP)."""

    def __init__(self, max_attempts: int, window_seconds: int):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._hits: Dict[str, List[float]] = defaultdict(list)
        self._lock = Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] < cutoff:
                hits.pop(0)
            if len(hits) >= self.max_attempts:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many attempts. Please try again later.",
                )
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


auth_rate_limiter = InMemoryRateLimiter(
    max_attempts=settings.auth_rate_limit_max_attempts,
    window_seconds=settings.auth_rate_limit_window_seconds,
)


def enforce_auth_rate_limit(request: Request) -> None:
    client_key = request.client.host if request.client else "unknown"
    auth_rate_limiter.check(client_key)
