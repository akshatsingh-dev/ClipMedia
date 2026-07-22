from types import SimpleNamespace

import pytest

from services.api.ratelimit import (
    InMemoryRateLimiter,
    Limit,
    client_key,
)


def test_allows_up_to_limit():
    rl = InMemoryRateLimiter()
    lim = Limit(max_requests=3, window_s=60)
    assert [rl.check("k", lim, now=0) for _ in range(3)] == [True, True, True]
    assert rl.check("k", lim, now=0) is False


def test_window_slides():
    """Requests aging out of the window free up capacity."""
    rl = InMemoryRateLimiter()
    lim = Limit(max_requests=2, window_s=60)
    assert rl.check("k", lim, now=0)
    assert rl.check("k", lim, now=1)
    assert rl.check("k", lim, now=2) is False
    # 61s later the first two have expired.
    assert rl.check("k", lim, now=62) is True


def test_keys_are_isolated():
    rl = InMemoryRateLimiter()
    lim = Limit(max_requests=1, window_s=60)
    assert rl.check("a", lim, now=0)
    assert rl.check("b", lim, now=0)
    assert rl.check("a", lim, now=0) is False


def test_retry_after():
    rl = InMemoryRateLimiter()
    lim = Limit(max_requests=1, window_s=60)
    rl.check("k", lim, now=0)
    assert rl.retry_after("k", lim, now=10) == pytest.approx(50.0)
    assert rl.retry_after("unknown", lim, now=0) == 0.0


def test_client_key_prefers_forwarded_ip():
    req = SimpleNamespace(
        headers={"x-forwarded-for": "1.2.3.4, 5.6.7.8"},
        client=SimpleNamespace(host="10.0.0.1"),
    )
    assert client_key(req) == "1.2.3.4"


def test_client_key_falls_back_to_peer():
    req = SimpleNamespace(headers={}, client=SimpleNamespace(host="10.0.0.1"))
    assert client_key(req) == "10.0.0.1"


def test_client_key_unknown():
    req = SimpleNamespace(headers={}, client=None)
    assert client_key(req) == "unknown"
