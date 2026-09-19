import asyncio
import time
from collections.abc import Callable

from app.application.ports.language_model import LanguageModel


class LanguageModelHealthCheck:
    """Exposes any LanguageModel as a HealthCheck so readiness stays one uniform list.

    ``GET /health/ready`` is public and a real adapter's ``check()`` is an outbound call
    carrying the API key, so the result (a failure too) is reused for ``cache_seconds``:
    however often readiness is hit, the provider is asked once per window.
    """

    name = "ai"

    def __init__(
        self,
        language_model: LanguageModel,
        *,
        cache_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._language_model = language_model
        self._cache_seconds = cache_seconds
        self._clock = clock
        self._checked: tuple[float, bool] | None = None
        # Concurrent readiness requests wait for the one call instead of each making their own.
        self._lock = asyncio.Lock()

    async def check(self) -> bool:
        async with self._lock:
            if self._checked is not None:
                at, healthy = self._checked
                if self._clock() - at < self._cache_seconds:
                    return healthy
            try:
                healthy = bool(await self._language_model.check())
            except asyncio.CancelledError:
                # Readiness ran out of patience first: a provider that hangs has failed, and
                # it is the one that must not be asked again on every hit.
                self._checked = (self._clock(), False)
                raise
            except Exception:
                healthy = False
            self._checked = (self._clock(), healthy)
            return healthy
