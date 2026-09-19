from datetime import timedelta
from typing import Protocol


class OneTimeStore(Protocol):
    """Short-lived values that can be read exactly once."""

    async def put(self, key: str, value: str, *, ttl: timedelta) -> None:
        """Keep ``value`` under ``key`` for ``ttl``. Raises ``ValueError`` unless ``ttl`` is
        positive."""
        ...

    async def take(self, key: str) -> str | None:
        """Return the value and delete it, atomically: of concurrent takers exactly one gets
        it. ``None`` when the key is unknown, already taken or expired."""
        ...
