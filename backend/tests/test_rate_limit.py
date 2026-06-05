import pytest
from fastapi import HTTPException

from app.core.rate_limit import RateLimitRule, RateLimiter


def test_rate_limiter_allows_requests_under_limit():
    limiter = RateLimiter()
    rule = RateLimitRule(max_requests=3, window_seconds=60)

    for _ in range(3):
        limiter.check("test-key", rule)


def test_rate_limiter_blocks_when_limit_exceeded():
    limiter = RateLimiter()
    rule = RateLimitRule(max_requests=2, window_seconds=60)

    limiter.check("test-key", rule)
    limiter.check("test-key", rule)

    with pytest.raises(HTTPException) as exc:
        limiter.check("test-key", rule)

    assert exc.value.status_code == 429


def test_rate_limiter_tracks_keys_independently():
    limiter = RateLimiter()
    rule = RateLimitRule(max_requests=1, window_seconds=60)

    limiter.check("key-a", rule)
    limiter.check("key-b", rule)

    with pytest.raises(HTTPException):
        limiter.check("key-a", rule)
