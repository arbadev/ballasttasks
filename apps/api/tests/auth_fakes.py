"""Hand-written test doubles for the user and authentication ports.

They pass the same contract suites as the real adapters (``tests/contract``).
"""

import itertools
import uuid
from datetime import UTC, datetime, timedelta

from app.application.errors import EmailAlreadyRegisteredError, InvalidTokenError
from app.domain.user import User


def a_user(*, is_active: bool = True) -> User:
    """A user nobody logs in as: someone to create tasks or to be assigned them."""
    return User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        full_name="Grace Hopper",
        hashed_password="not-a-real-hash",
        is_active=is_active,
        created_at=datetime(2026, 1, 5, 9, 0, tzinfo=UTC),
    )


def _refuse_nul(*values: str) -> None:
    if any("\x00" in value for value in values):
        raise ValueError("PostgreSQL text cannot contain NUL (0x00) characters")


class InMemoryUserRepository:
    """UserRepository double: a dict, with the same uniqueness rule as the real table.

    Like PostgreSQL text, it cannot hold or compare a NUL character: a caller that lets one
    through fails here as it would against the real database.
    """

    def __init__(self) -> None:
        self._users: dict[uuid.UUID, User] = {}

    async def add(self, user: User) -> None:
        _refuse_nul(user.email, user.full_name, user.hashed_password)
        if any(existing.email == user.email for existing in self._users.values()):
            raise EmailAlreadyRegisteredError(user.email)
        self._users[user.id] = user

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return self._users.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        _refuse_nul(email)
        return next((user for user in self._users.values() if user.email == email), None)


class InMemoryUserDirectory:
    """UserDirectory double: reads the users fake, so whoever registered can be assigned."""

    def __init__(self, users: InMemoryUserRepository) -> None:
        self._users = users

    async def is_active_user(self, user_id: uuid.UUID) -> bool:
        user = await self._users.get_by_id(user_id)
        return user is not None and user.is_active


class FakePasswordHasher:
    """PasswordHasher double: reversible and instant, but salted like a real one."""

    PREFIX = "fake-hash"

    def __init__(self) -> None:
        self._salts = itertools.count(1)

    def hash(self, password: str) -> str:
        return f"{self.PREFIX}${next(self._salts)}${password}"

    def verify(self, password: str, hashed_password: str) -> bool:
        prefix, _, rest = hashed_password.partition("$")
        _, _, original = rest.partition("$")
        return prefix == self.PREFIX and original == password


class FakeTokenService:
    """TokenService double: opaque random tokens held in memory, with a real expiry."""

    def __init__(self, *, expires_in: timedelta = timedelta(minutes=30)) -> None:
        self._expires_in = expires_in
        self._issued: dict[str, tuple[uuid.UUID, datetime]] = {}

    def issue(self, user_id: uuid.UUID) -> str:
        token = f"fake-token-{uuid.uuid4().hex}"
        self._issued[token] = (user_id, datetime.now(UTC) + self._expires_in)
        return token

    def decode(self, token: str) -> uuid.UUID:
        issued = self._issued.get(token)
        if issued is None or issued[1] <= datetime.now(UTC):
            raise InvalidTokenError
        return issued[0]
