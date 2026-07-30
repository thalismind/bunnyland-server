"""Small overload guards for application request and connection boundaries."""

from __future__ import annotations

import math
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from threading import Lock

#: Cap on distinct caller buckets held at once. Some limiters are keyed by values the
#: caller chooses -- the login limiter keys on the submitted username -- and cleanup only
#: ran once per window, so a flood of unique keys grew the map unboundedly between sweeps.
#: Past the cap the least recently seen bucket is dropped; a caller that loses its bucket
#: is only ever granted a fresh allowance, never denied one it should have had.
MAX_TRACKED_KEYS = 8192


class FixedWindowRateLimiter:
    def __init__(
        self,
        requests: int,
        window_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_tracked_keys: int = MAX_TRACKED_KEYS,
    ) -> None:
        self.requests = max(0, int(requests))
        self.window_seconds = max(0.001, float(window_seconds))
        self.max_tracked_keys = max(1, int(max_tracked_keys))
        self._clock = clock
        self._requests: OrderedDict[str, deque[float]] = OrderedDict()
        self._last_cleanup = 0.0
        self._lock = Lock()

    def check(self, key: str, *, now: float | None = None) -> tuple[bool, int]:
        """Return ``(allowed, retry_after_seconds)`` for one caller key."""

        if self.requests == 0:
            return True, 0
        current = self._clock() if now is None else now
        cutoff = current - self.window_seconds
        with self._lock:
            if current - self._last_cleanup >= self.window_seconds:
                stale = [
                    caller
                    for caller, entries in self._requests.items()
                    if not entries or entries[-1] <= cutoff
                ]
                for caller in stale:
                    del self._requests[caller]
                self._last_cleanup = current
            entries = self._requests.setdefault(key, deque())
            self._requests.move_to_end(key)
            while len(self._requests) > self.max_tracked_keys:
                self._requests.popitem(last=False)
            while entries and entries[0] <= cutoff:
                entries.popleft()
            if len(entries) >= self.requests:
                retry_after = max(1, math.ceil(entries[0] + self.window_seconds - current))
                return False, retry_after
            entries.append(current)
        return True, 0

    def reset(self, key: str) -> None:
        """Forget one caller bucket after a successful authentication."""

        with self._lock:
            self._requests.pop(key, None)


class ConcurrencyLimiter:
    """Cap how many long-lived connections one identity holds open at once.

    A rate limiter bounds how fast connections are opened, not how many are held. A
    websocket is a single request that then lives for as long as the client wants, so the
    request limiter never saw it again after the upgrade and one caller could accumulate
    sockets indefinitely -- each costing a task, a queue, and an upstream proxy connection.
    """

    def __init__(self, limit: int) -> None:
        #: ``0`` disables the cap, matching FixedWindowRateLimiter's convention.
        self.limit = max(0, int(limit))
        self._held: dict[str, int] = {}
        self._lock = Lock()

    def acquire(self, key: str) -> bool:
        """Take a slot for ``key``, returning ``False`` when it is already at the cap."""

        if self.limit == 0:
            return True
        with self._lock:
            current = self._held.get(key, 0)
            if current >= self.limit:
                return False
            self._held[key] = current + 1
        return True

    def release(self, key: str) -> None:
        if self.limit == 0:
            return
        with self._lock:
            current = self._held.get(key, 0) - 1
            # Dropping the key at zero keeps this map proportional to live connections
            # rather than to every identity ever seen.
            if current > 0:
                self._held[key] = current
            else:
                self._held.pop(key, None)

    @contextmanager
    def slot(self, key: str) -> Iterator[bool]:
        """Hold a slot for the duration of the block, releasing it however the block exits."""

        acquired = self.acquire(key)
        try:
            yield acquired
        finally:
            if acquired:
                self.release(key)


__all__ = ["MAX_TRACKED_KEYS", "ConcurrencyLimiter", "FixedWindowRateLimiter"]
