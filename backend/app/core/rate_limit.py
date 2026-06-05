import time
from collections import defaultdict
from dataclasses import dataclass
from threading import Lock

from fastapi import HTTPException, Request

from app.core.config import get_settings


@dataclass(frozen=True)
class RateLimitRule:
    max_requests: int
    window_seconds: int


class RateLimiter:
    def __init__(self, max_keys: int = 10_000) -> None:
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()
        self._max_keys = max_keys

    def _prune_bucket(self, key: str, window_seconds: int) -> list[float]:
        now = time.monotonic()
        cutoff = now - window_seconds
        bucket = [t for t in self._hits[key] if t > cutoff]
        if bucket:
            self._hits[key] = bucket
        elif key in self._hits:
            del self._hits[key]
        return bucket

    def _evict_if_needed(self, window_seconds: int) -> None:
        if len(self._hits) <= self._max_keys:
            return
        now = time.monotonic()
        cutoff = now - window_seconds
        stale = [key for key, hits in self._hits.items() if not hits or hits[-1] <= cutoff]
        for key in stale:
            del self._hits[key]

    def check(self, key: str, rule: RateLimitRule) -> None:
        with self._lock:
            bucket = self._prune_bucket(key, rule.window_seconds)
            if len(bucket) >= rule.max_requests:
                raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试。")
            bucket.append(time.monotonic())
            self._hits[key] = bucket
            self._evict_if_needed(rule.window_seconds)


def resolve_client_ip(
    peer_host: str | None,
    forwarded_for: str | None,
    real_ip: str | None,
    trusted_proxies: frozenset[str],
) -> str:
    peer = peer_host or "unknown"
    if trusted_proxies and peer in trusted_proxies:
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        if real_ip:
            return real_ip.strip()
    return peer


def client_ip(request: Request) -> str:
    settings = get_settings()
    peer = request.client.host if request.client else None
    return resolve_client_ip(
        peer_host=peer,
        forwarded_for=request.headers.get("X-Forwarded-For"),
        real_ip=request.headers.get("X-Real-IP"),
        trusted_proxies=settings.trusted_proxy_set(),
    )


_settings = get_settings()
limiter = RateLimiter(max_keys=_settings.rate_limit_max_keys)

LOGIN_RATE = RateLimitRule(max_requests=10, window_seconds=60)
REGISTER_RATE = RateLimitRule(max_requests=5, window_seconds=3600)
BOOTSTRAP_RATE = RateLimitRule(max_requests=3, window_seconds=3600)
STREAM_RATE = RateLimitRule(max_requests=30, window_seconds=60)
UPLOAD_RATE = RateLimitRule(max_requests=10, window_seconds=3600)
REINDEX_RATE = RateLimitRule(max_requests=5, window_seconds=3600)


def enforce_rate_limit(request: Request, rule: RateLimitRule, *, scope: str) -> None:
    limiter.check(f"{scope}:ip:{client_ip(request)}", rule)


def enforce_user_rate_limit(user_id: str, rule: RateLimitRule, *, scope: str) -> None:
    limiter.check(f"{scope}:user:{user_id}", rule)


def reset_rate_limiter_for_tests() -> None:
    with limiter._lock:
        limiter._hits.clear()
