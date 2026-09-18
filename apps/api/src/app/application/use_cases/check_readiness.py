import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from app.application.ports.health_check import HealthCheck

DEFAULT_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    healthy: bool


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    results: tuple[CheckResult, ...]

    @property
    def ready(self) -> bool:
        return all(result.healthy for result in self.results)

    @property
    def failed(self) -> tuple[str, ...]:
        return tuple(result.name for result in self.results if not result.healthy)


class CheckReadiness:
    """Runs every registered health check concurrently and reports each outcome.

    A check that raises or exceeds the timeout counts as failed: readiness must
    always produce a report, never an error.
    """

    def __init__(
        self,
        checks: Sequence[HealthCheck],
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._checks = tuple(checks)
        self._timeout_seconds = timeout_seconds

    async def execute(self) -> ReadinessReport:
        results = await asyncio.gather(*(self._run(check) for check in self._checks))
        return ReadinessReport(results=tuple(results))

    async def _run(self, check: HealthCheck) -> CheckResult:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                healthy = bool(await check.check())
        except Exception:  # a misbehaving adapter must not take readiness down with it
            healthy = False
        return CheckResult(name=check.name, healthy=healthy)
