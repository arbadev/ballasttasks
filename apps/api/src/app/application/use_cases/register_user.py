import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from app.application.errors import EmailAlreadyRegisteredError
from app.application.ports.password_hasher import PasswordHasher
from app.application.ports.user_repository import UserRepository
from app.domain.user import User, normalise_email


def _utc_now() -> datetime:
    return datetime.now(UTC)


class RegisterUser:
    """Creates an active user with a hashed password.

    The lookup gives a cheap, early rejection; the repository's uniqueness rule is what
    makes two concurrent registrations of one email safe.
    """

    def __init__(
        self,
        users: UserRepository,
        hasher: PasswordHasher,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._users = users
        self._hasher = hasher
        self._clock = clock

    async def execute(self, *, email: str, full_name: str, password: str) -> User:
        email = normalise_email(email)
        if await self._users.get_by_email(email) is not None:
            raise EmailAlreadyRegisteredError(email)
        user = User(
            id=uuid.uuid4(),
            email=email,
            full_name=full_name.strip(),
            # Hashing is deliberately slow: keep it off the event loop.
            hashed_password=await asyncio.to_thread(self._hasher.hash, password),
            is_active=True,
            created_at=self._clock(),
        )
        await self._users.add(user)
        return user
