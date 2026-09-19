from dataclasses import dataclass

from app.application.clock import Clock, utc_now
from app.application.ports.rate_limiter import RateLimitDecision, RateLimitPolicy
from app.infrastructure.rate_limit.window import decision

DEFAULT_MAX_KEYS = 10_000


@dataclass(slots=True)
class _Window:
    ends_ms: float
    count: int = 0


class InMemoryRateLimiter:
    """The same fixed window as ``RedisRateLimiter``, counted in this process only.

    Two jobs: the limiter of the tests, and the stand-in while Redis is unreachable
    (``FailOpenRateLimiter``). It is NOT a production limiter on its own: every API process
    would allow the full limit, and a restart forgets every count.

    ``hit`` never awaits, so on one event loop it is atomic without a lock.
    Memory is bounded: expired windows are dropped once ``max_keys`` are tracked, and if every
    tracked window is still live a new key is allowed without being tracked. Under a flood of
    distinct keys it limits less; it never grows without bound and never refuses wrongly.
    """

    def __init__(self, *, clock: Clock = utc_now, max_keys: int = DEFAULT_MAX_KEYS) -> None:
        self._clock = clock
        self._max_keys = max_keys
        self._windows: dict[tuple[str, str], _Window] = {}

    @property
    def tracked_keys(self) -> int:
        return len(self._windows)

    async def hit(self, key: str, policy: RateLimitPolicy) -> RateLimitDecision:
        now_ms = self._clock().timestamp() * 1000
        window_ms = policy.window_seconds * 1000
        identity = (policy.name, key)
        window = self._windows.get(identity)
        if window is None or now_ms >= window.ends_ms:
            window = _Window(ends_ms=now_ms + window_ms)
            if not self._has_room_for(identity, now_ms):
                return decision(policy, allowed=True, count=1, reset_after_ms=window_ms)
            self._windows[identity] = window
        allowed = window.count < policy.limit
        if allowed:
            window.count += 1
        return decision(
            policy, allowed=allowed, count=window.count, reset_after_ms=window.ends_ms - now_ms
        )

    def _has_room_for(self, identity: tuple[str, str], now_ms: float) -> bool:
        if identity in self._windows or len(self._windows) < self._max_keys:
            return True
        self._windows = {
            tracked: window for tracked, window in self._windows.items() if now_ms < window.ends_ms
        }
        return len(self._windows) < self._max_keys
