"""The arithmetic both adapters share, so "seconds until reset" means the same on each."""

import math

from app.application.ports.rate_limiter import RateLimitDecision, RateLimitPolicy


def decision(
    policy: RateLimitPolicy, *, allowed: bool, count: int, reset_after_ms: float
) -> RateLimitDecision:
    return RateLimitDecision(
        allowed=allowed,
        limit=policy.limit,
        remaining=max(policy.limit - count, 0),
        # Rounded up: a client that waits this long never arrives before the window ends.
        reset_after_seconds=max(math.ceil(reset_after_ms / 1000), 1),
    )
