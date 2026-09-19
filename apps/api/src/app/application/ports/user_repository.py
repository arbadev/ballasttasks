import uuid
from typing import Protocol

from app.domain.user import User


class UserRepository(Protocol):
    """Persistence for users. Emails are already normalised by the ``User`` entity."""

    async def add(self, user: User) -> None:
        """Store a new user.

        Raises ``EmailAlreadyRegisteredError`` when the email is taken, including when a
        concurrent ``add`` won the race: uniqueness is the repository's guarantee.
        """
        ...

    async def get_by_id(self, user_id: uuid.UUID) -> User | None: ...

    async def get_by_email(self, email: str) -> User | None:
        """Look up by normalised email; ``None`` when there is no such user."""
        ...

    async def update(self, user: User) -> None:
        """Store the current profile (full name, role label) of an existing user.

        Raises ``UserNotFound``.
        """
        ...
