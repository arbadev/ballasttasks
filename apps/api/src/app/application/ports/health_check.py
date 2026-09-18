from typing import Protocol


class HealthCheck(Protocol):
    """Liveness probe for one dependency of the system."""

    @property
    def name(self) -> str:
        """Stable identifier reported to clients (e.g. ``database``)."""
        ...

    async def check(self) -> bool:
        """Return True when the dependency is usable. Must never raise."""
        ...
