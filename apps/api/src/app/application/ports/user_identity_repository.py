import uuid
from datetime import datetime
from typing import Protocol


class UserIdentityRepository(Protocol):
    """Which user an identity at an external provider belongs to."""

    async def find_user_id(self, provider: str, subject: str) -> uuid.UUID | None: ...

    async def link(
        self, user_id: uuid.UUID, provider: str, subject: str, *, linked_at: datetime
    ) -> None:
        """Record that ``(provider, subject)`` is ``user_id``.

        Raises ``IdentityAlreadyLinkedError`` when that identity already belongs to a user
        or the user already has an identity at that provider, including when a concurrent
        ``link`` won the race: uniqueness is the repository's guarantee.
        """
        ...
