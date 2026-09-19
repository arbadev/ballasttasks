from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    """At most ``limit`` hits per key in any one window of ``window_seconds``.

    ``name`` is part of the counter's identity: one key under two policies is counted twice,
    separately.
    """

    name: str
    limit: int
    window_seconds: int

    def __post_init__(self) -> None:
        if self.limit <= 0 or self.window_seconds <= 0:
            raise ValueError(f"policy {self.name!r}: limit and window_seconds must be positive")


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int  # hits left in the current window; 0 when not allowed
    reset_after_seconds: int  # rounded up, so waiting this long is always long enough


class RateLimiter(Protocol):
    """Counts hits per key and says whether the next one is within the policy."""

    async def hit(self, key: str, policy: RateLimitPolicy) -> RateLimitDecision:
        """Record one hit and decide it, atomically: concurrent hits never exceed the limit.

        A hit that is not allowed is not counted and does not extend the window.
        """
        ...
