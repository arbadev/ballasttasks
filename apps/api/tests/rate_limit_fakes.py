"""Hand-written test doubles for the rate limiter: a clock the test moves, and limiters
that fail the way an unreachable Redis does."""

import asyncio
from datetime import UTC, datetime, timedelta

from app.application.ports.rate_limiter import RateLimitDecision, RateLimiter, RateLimitPolicy


class FakeClock:
    """A ``Clock`` that only moves when the test says so."""

    def __init__(self) -> None:
        self.now = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class FakeMonotonic:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class SwitchableRateLimiter:
    """Delegates to a real limiter until the test takes it ``down``; counts every call."""

    # Looks like a Redis URL with a password: nothing of it may reach a log line.
    SECRET_BEARING_MESSAGE = "Error connecting to redis://:s3cret-password@cache:6379"

    def __init__(self, delegate: RateLimiter) -> None:
        self._delegate = delegate
        self.down = False
        self.calls = 0

    async def hit(self, key: str, policy: RateLimitPolicy) -> RateLimitDecision:
        self.calls += 1
        if self.down:
            raise ConnectionError(self.SECRET_BEARING_MESSAGE)
        return await self._delegate.hit(key, policy)


class HangingRateLimiter:
    """A limiter whose backend accepts the connection and then never answers."""

    async def hit(self, key: str, policy: RateLimitPolicy) -> RateLimitDecision:
        await asyncio.sleep(60)
        raise AssertionError("unreachable: the caller should have timed out")
