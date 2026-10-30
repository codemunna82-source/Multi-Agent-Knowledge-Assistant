"""Fixed-window rate limiting; Redis-backed when MKA_REDIS_URL is set (shared across replicas), else in-process."""
from __future__ import annotations

import threading
import time
from typing import Optional

UNITS = {"second": 1, "minute": 60, "hour": 3600}


def parse_limit(spec: str) -> tuple[int, int]:
    n, _, unit = spec.partition("/")
    if unit not in UNITS or not n.isdigit() or int(n) < 1:
        raise ValueError(f"Invalid rate limit '{spec}' (expected e.g. 30/minute)")
    return int(n), UNITS[unit]


class RateLimiter:
    def __init__(self, redis_client=None, enabled: bool = True):
        self.redis, self.enabled = redis_client, enabled
        self._mem: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, spec: str) -> tuple[bool, int]:
        """-> (allowed, retry_after_seconds)"""
        if not self.enabled:
            return True, 0
        limit, window = parse_limit(spec)
        bucket = int(time.time() // window)
        k = f"rl:{key}:{bucket}"
        retry = window - int(time.time() % window)
        if self.redis is not None:
            pipe = self.redis.pipeline()
            pipe.incr(k)
            pipe.expire(k, window + 1)
            count = pipe.execute()[0]
            return count <= limit, retry
        with self._lock:
            if len(self._mem) > 10000:  # drop expired buckets
                now = time.time()
                self._mem = {a: b for a, b in self._mem.items() if b[1] > now}
            count, exp = self._mem.get(k, (0, time.time() + window + 1))
            self._mem[k] = (count + 1, exp)
        return count + 1 <= limit, retry
