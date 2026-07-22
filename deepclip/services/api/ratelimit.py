"""Rate limiting for the expensive endpoints.

Each uncached build costs ~$1 (C8) and `/api/build` and `/api/import` both
enqueue paid work. Unthrottled, one script can run up a bill or exhaust the
YouTube quota for everyone. This caps requests per client per window.

Backed by Redis when available (correct across multiple API processes, which is
the deployed topology), with an in-memory fallback so a single dev process is
still protected. The fallback is per-process, so it is not a substitute for
Redis at scale — it is a floor, not the ceiling.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class Limit:
    max_requests: int
    window_s: float


# Build and import are the paid paths. Events and reads are cheap and not limited
# here (events are already fire-and-forget and capped at 100/batch).
BUILD_LIMIT = Limit(max_requests=5, window_s=60.0)
IMPORT_LIMIT = Limit(max_requests=5, window_s=60.0)


@dataclass
class InMemoryRateLimiter:
    """Sliding-window counter per key. Single-process only."""

    _hits: dict[str, deque] = field(default_factory=dict)

    def check(self, key: str, limit: Limit, now: float | None = None) -> bool:
        """True if allowed. Records the hit when allowed."""
        now = now if now is not None else time.monotonic()
        dq = self._hits.setdefault(key, deque())
        cutoff = now - limit.window_s
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= limit.max_requests:
            return False
        dq.append(now)
        return True

    def retry_after(self, key: str, limit: Limit, now: float | None = None) -> float:
        """Seconds until the oldest hit in the window expires."""
        now = now if now is not None else time.monotonic()
        dq = self._hits.get(key)
        if not dq:
            return 0.0
        return max(0.0, limit.window_s - (now - dq[0]))


class RedisRateLimiter:
    """Cross-process limiter using a Redis sorted set per key.

    Members are timestamps; the window is trimmed on each check. Correct when
    several API processes share one Redis, which the in-memory version is not.
    """

    def __init__(self, redis):
        self._redis = redis

    async def check(self, key: str, limit: Limit) -> bool:
        now = time.time()
        rkey = f"ratelimit:{key}"
        cutoff = now - limit.window_s
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.zremrangebyscore(rkey, 0, cutoff)
            pipe.zcard(rkey)
            pipe.zadd(rkey, {f"{now}": now})
            pipe.expire(rkey, int(limit.window_s) + 1)
            _, count, _, _ = await pipe.execute()
        # count is the size BEFORE this request was added.
        return count < limit.max_requests


def client_key(request) -> str:
    """Identify the caller for limiting.

    Prefers a forwarded client IP (behind a proxy/CDN in production), falls back
    to the socket peer. Not spoof-proof on its own — a real deployment pairs this
    with the proxy setting a trusted header — but it stops casual abuse.
    """
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    client = getattr(request, "client", None)
    return client.host if client else "unknown"
