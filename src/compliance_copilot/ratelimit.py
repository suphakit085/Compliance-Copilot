"""Small in-process sliding-window rate limiter.

Protects the expensive endpoints (every chat answer is an LLM call) and slows password
guessing. State lives in this process: with several API replicas each enforces its own
window, so a shared store (Redis) or the API gateway should enforce the same limits in
production - the limits below are the application-level backstop, not a replacement.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._warned: dict[str, float] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_s: float, now: float | None = None) -> tuple[float, bool]:
        """Record one request. Returns (retry_after_seconds, first_violation); 0 means allowed."""
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and q[0] <= now - window_s:
                q.popleft()
            if len(q) >= limit:
                first = self._warned.get(key, -1e18) <= now - window_s
                if first:
                    self._warned[key] = now
                return max(q[0] + window_s - now, 1.0), first
            q.append(now)
            if len(self._hits) > 10_000:  # bound memory under key-spraying
                self._prune(now, window_s)
            return 0.0, False

    def _prune(self, now: float, window_s: float) -> None:
        for k in [k for k, q in self._hits.items() if not q or q[-1] <= now - window_s]:
            self._hits.pop(k, None)
            self._warned.pop(k, None)

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
                self._warned.clear()
            else:
                self._hits.pop(key, None)
                self._warned.pop(key, None)


limiter = RateLimiter()
