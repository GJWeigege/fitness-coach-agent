import time
from collections import defaultdict
from threading import Lock

from fastapi import HTTPException


class LoginLockout:
    def __init__(self, max_keys: int = 10_000) -> None:
        self._failures: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()
        self._max_keys = max_keys

    def _normalize(self, username: str) -> str:
        return username.strip().lower()

    def _prune(self, key: str, window_seconds: int) -> list[float]:
        now = time.monotonic()
        cutoff = now - window_seconds
        bucket = [t for t in self._failures[key] if t > cutoff]
        if bucket:
            self._failures[key] = bucket
        elif key in self._failures:
            del self._failures[key]
        return bucket

    def _evict_if_needed(self, window_seconds: int) -> None:
        if len(self._failures) <= self._max_keys:
            return
        now = time.monotonic()
        cutoff = now - window_seconds
        stale = [key for key, hits in self._failures.items() if not hits or hits[-1] <= cutoff]
        for key in stale:
            del self._failures[key]

    def check_allowed(self, username: str, *, max_attempts: int, window_seconds: int) -> None:
        key = self._normalize(username)
        with self._lock:
            bucket = self._prune(key, window_seconds)
            if len(bucket) >= max_attempts:
                raise HTTPException(status_code=429, detail="登录失败次数过多，请稍后再试。")

    def record_failure(self, username: str, *, window_seconds: int) -> None:
        key = self._normalize(username)
        with self._lock:
            bucket = self._prune(key, window_seconds)
            bucket.append(time.monotonic())
            self._failures[key] = bucket
            self._evict_if_needed(window_seconds)

    def record_success(self, username: str) -> None:
        key = self._normalize(username)
        with self._lock:
            self._failures.pop(key, None)

    def reset_for_tests(self) -> None:
        with self._lock:
            self._failures.clear()


login_lockout = LoginLockout()
