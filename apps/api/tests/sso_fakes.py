"""Hand-written test doubles for the single sign-on ports.

They pass the same contract suites as the real adapters (``tests/contract``). The
``IdentityProvider`` double is not here: ``FakeIdentityProvider`` is a registered adapter
(``app.infrastructure.identity.fake``), because local demos use it too.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from app.application.errors import IdentityAlreadyLinkedError
from app.application.ports.identity_provider import VerifiedIdentity


def an_identity(**overrides: object) -> VerifiedIdentity:
    fields: dict[str, object] = {
        "provider": "fake",
        "subject": f"subject-{uuid.uuid4().hex}",
        "email": f"{uuid.uuid4().hex}@example.com",
        "email_verified": True,
        "full_name": "Ada Lovelace",
    }
    return VerifiedIdentity(**{**fields, **overrides})  # type: ignore[arg-type]


class MutableClock:
    """A clock the test moves by hand, so expiry needs no sleeping."""

    def __init__(self, now: datetime = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


def _utc_now() -> datetime:
    return datetime.now(UTC)


class InMemoryOneTimeStore:
    """OneTimeStore double: a dict with expiry; ``take`` removes what it returns."""

    def __init__(self, clock: Callable[[], datetime] = _utc_now) -> None:
        self._clock = clock
        self._values: dict[str, tuple[str, datetime]] = {}

    async def put(self, key: str, value: str, *, ttl: timedelta) -> None:
        if ttl <= timedelta(0):
            raise ValueError("ttl must be positive")
        self._values[key] = (value, self._clock() + ttl)

    async def take(self, key: str) -> str | None:
        stored = self._values.pop(key, None)
        if stored is None or stored[1] <= self._clock():
            return None
        return stored[0]

    def stored_keys(self) -> list[str]:
        """Test-only: what is stored, to prove that no secret is kept as a key."""
        return list(self._values)


class InMemoryUserIdentityRepository:
    """UserIdentityRepository double with the two uniqueness rules of the real table."""

    def __init__(self) -> None:
        self._links: dict[tuple[str, str], uuid.UUID] = {}

    async def find_user_id(self, provider: str, subject: str) -> uuid.UUID | None:
        return self._links.get((provider, subject))

    async def link(
        self, user_id: uuid.UUID, provider: str, subject: str, *, linked_at: datetime
    ) -> None:
        taken = (provider, subject) in self._links
        has_one = any(
            linked_provider == provider and linked_user == user_id
            for (linked_provider, _), linked_user in self._links.items()
        )
        if taken or has_one:
            raise IdentityAlreadyLinkedError
        self._links[(provider, subject)] = user_id


class StubIdentityProvider:
    """An IdentityProvider whose answer the test decides: an identity, or an error."""

    def __init__(self, name: str, outcome: VerifiedIdentity | Exception) -> None:
        self.name = name
        self.outcome = outcome
        self.exchanges: list[dict[str, str]] = []

    async def authorization_url(self, *, state: str, nonce: str, redirect_uri: str) -> str:
        return f"https://idp.example/authorize?state={state}&nonce={nonce}"

    async def exchange(self, *, code: str, redirect_uri: str, nonce: str) -> VerifiedIdentity:
        self.exchanges.append({"code": code, "redirect_uri": redirect_uri, "nonce": nonce})
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome
