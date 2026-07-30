"""Small fixed-window overload guard for application request boundaries."""

from __future__ import annotations

import math
import time
from collections import OrderedDict, deque
from collections.abc import Callable
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


__all__ = ["MAX_TRACKED_KEYS", "FixedWindowRateLimiter"]
