import asyncio
import logging
import time
from collections.abc import Callable

from app.application.ports.rate_limiter import RateLimitDecision, RateLimiter, RateLimitPolicy

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 0.5
DEFAULT_RETRY_AFTER_SECONDS = 5.0


class FailOpenRateLimiter:
    """Keeps the API serving while the primary limiter (Redis) is unreachable.

    Rate limiting protects the API; it must never be the reason the API is down. So a
    primary that raises, or takes longer than ``timeout_seconds``, never becomes an error:
    the hit is decided by ``fallback`` (an in-process limiter) instead. That is fail OPEN:
    each process then allows up to the full limit on its own, which is looser than the
    shared count but still stops a single-connection brute force.

    One outage, one warning. After a failure the primary is left alone for
    ``retry_after_seconds``, then ONE request probes it while the others keep using the
    fallback; so an outage costs a request per interval, not a timeout per request. Only a
    successful probe ends the outage (logged once, at INFO). Late answers from calls that
    started before the outage are ignored, so a flapping backend cannot log per request.

    The log line carries the error's type, never its message or traceback: a Redis error can
    quote the connection URL, and a URL can hold a password.
    """

    def __init__(
        self,
        primary: RateLimiter,
        fallback: RateLimiter,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        retry_after_seconds: float = DEFAULT_RETRY_AFTER_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._timeout_seconds = timeout_seconds
        self._retry_after_seconds = retry_after_seconds
        self._monotonic = monotonic
        self._in_outage = False
        self._probe_at = 0.0

    async def hit(self, key: str, policy: RateLimitPolicy) -> RateLimitDecision:
        probing = self._in_outage
        if probing:
            if self._monotonic() < self._probe_at:
                return await self._fallback.hit(key, policy)
            # Claimed before awaiting, so concurrent requests do not all probe at once.
            self._probe_at = self._monotonic() + self._retry_after_seconds
        try:
            async with asyncio.timeout(self._timeout_seconds):
                decision = await self._primary.hit(key, policy)
        except Exception as error:
            self._primary_failed(error)
            return await self._fallback.hit(key, policy)
        if probing and self._in_outage:
            self._in_outage = False
            logger.info("Rate limiter backend is reachable again: shared rate limits restored")
        return decision

    def _primary_failed(self, error: Exception) -> None:
        self._probe_at = self._monotonic() + self._retry_after_seconds
        if not self._in_outage:
            self._in_outage = True
            logger.warning(
                "Rate limiter backend is unavailable (%s): requests are served and rate "
                "limits are counted per process until it answers again",
                type(error).__name__,
            )
