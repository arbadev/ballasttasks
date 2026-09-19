import dataclasses
import uuid
from datetime import UTC, datetime

import pytest

from app.application.errors import (
    EmailAlreadyRegisteredError,
    EmailNotVerifiedError,
    IdentityCodeRejectedError,
    SsoSignInRefusedError,
    UserNotActiveError,
)
from app.application.use_cases.sign_in_with_identity import SignInWithIdentity
from app.domain.user import User
from tests.auth_fakes import InMemoryUserRepository, a_user
from tests.sso_fakes import InMemoryUserIdentityRepository, an_identity

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)


@pytest.fixture
def users() -> InMemoryUserRepository:
    return InMemoryUserRepository()


@pytest.fixture
def identities() -> InMemoryUserIdentityRepository:
    return InMemoryUserIdentityRepository()


@pytest.fixture
def sign_in(
    users: InMemoryUserRepository, identities: InMemoryUserIdentityRepository
) -> SignInWithIdentity:
    return SignInWithIdentity(users, identities, clock=lambda: NOW)


async def test_a_first_sign_in_creates_an_active_user_without_a_password_and_links_it(
    sign_in: SignInWithIdentity,
    users: InMemoryUserRepository,
    identities: InMemoryUserIdentityRepository,
) -> None:
    identity = an_identity(email="  Ada@Example.com ", full_name="  Ada Lovelace ")

    user = await sign_in.execute(identity)

    assert user == await users.get_by_id(user.id)
    assert user.email == "ada@example.com"
    assert user.full_name == "Ada Lovelace"
    assert user.hashed_password is None
    assert user.is_active is True
    assert user.created_at == NOW
    assert await identities.find_user_id(identity.provider, identity.subject) == user.id


async def test_the_same_identity_signs_in_as_the_same_user_every_time(
    sign_in: SignInWithIdentity,
) -> None:
    identity = an_identity()

    first = await sign_in.execute(identity)
    second = await sign_in.execute(identity)

    assert second == first


async def test_a_linked_identity_follows_the_subject_not_the_email(
    sign_in: SignInWithIdentity, users: InMemoryUserRepository
) -> None:
    """The provider's subject is the stable key: a person who changes their address at the
    provider is still the same user, and no second account appears."""
    identity = an_identity()
    first = await sign_in.execute(identity)

    moved = dataclasses.replace(identity, email="new-address@example.com")
    second = await sign_in.execute(moved)

    assert second == first
    assert await users.get_by_email("new-address@example.com") is None


async def test_a_verified_email_links_to_the_existing_password_user_and_keeps_the_password(
    sign_in: SignInWithIdentity,
    users: InMemoryUserRepository,
    identities: InMemoryUserIdentityRepository,
) -> None:
    existing = a_user()
    await users.add(existing)
    identity = an_identity(email=existing.email.upper())

    user = await sign_in.execute(identity)

    assert user == existing
    assert user.hashed_password == existing.hashed_password
    assert await identities.find_user_id(identity.provider, identity.subject) == existing.id


async def test_an_unverified_email_is_refused_and_nothing_is_stored(
    sign_in: SignInWithIdentity,
    users: InMemoryUserRepository,
    identities: InMemoryUserIdentityRepository,
) -> None:
    identity = an_identity(email_verified=False)

    with pytest.raises(EmailNotVerifiedError):
        await sign_in.execute(identity)

    assert await users.get_by_email(identity.email) is None
    assert await identities.find_user_id(identity.provider, identity.subject) is None


async def test_an_unverified_email_never_links_to_an_existing_user(
    sign_in: SignInWithIdentity,
    users: InMemoryUserRepository,
    identities: InMemoryUserIdentityRepository,
) -> None:
    """The account-takeover case: anybody can claim an address the provider never checked."""
    victim = a_user()
    await users.add(victim)
    identity = an_identity(email=victim.email, email_verified=False)

    with pytest.raises(EmailNotVerifiedError):
        await sign_in.execute(identity)

    assert await identities.find_user_id(identity.provider, identity.subject) is None


async def test_an_unverified_email_is_refused_even_for_an_identity_linked_earlier(
    sign_in: SignInWithIdentity,
) -> None:
    identity = an_identity()
    await sign_in.execute(identity)

    with pytest.raises(EmailNotVerifiedError):
        await sign_in.execute(dataclasses.replace(identity, email_verified=False))


async def test_an_inactive_linked_user_cannot_sign_in(
    sign_in: SignInWithIdentity,
    users: InMemoryUserRepository,
    identities: InMemoryUserIdentityRepository,
) -> None:
    inactive = a_user(is_active=False)
    await users.add(inactive)
    identity = an_identity(email=inactive.email)
    await identities.link(inactive.id, identity.provider, identity.subject, linked_at=NOW)

    with pytest.raises(UserNotActiveError):
        await sign_in.execute(identity)


async def test_an_inactive_user_with_the_same_email_cannot_sign_in_and_is_not_linked(
    sign_in: SignInWithIdentity,
    users: InMemoryUserRepository,
    identities: InMemoryUserIdentityRepository,
) -> None:
    inactive = a_user(is_active=False)
    await users.add(inactive)
    identity = an_identity(email=inactive.email)

    with pytest.raises(UserNotActiveError):
        await sign_in.execute(identity)

    assert await identities.find_user_id(identity.provider, identity.subject) is None


async def test_a_link_to_a_user_who_no_longer_exists_cannot_sign_in(
    sign_in: SignInWithIdentity, identities: InMemoryUserIdentityRepository
) -> None:
    identity = an_identity()
    await identities.link(uuid.uuid4(), identity.provider, identity.subject, linked_at=NOW)

    with pytest.raises(UserNotActiveError):
        await sign_in.execute(identity)


async def test_a_second_subject_of_one_provider_is_never_linked_to_the_same_user(
    sign_in: SignInWithIdentity, identities: InMemoryUserIdentityRepository
) -> None:
    """A recycled address: the mailbox now belongs to somebody else at the provider. The
    email matches, the subject does not, and the user already has an identity there."""
    original = an_identity(email="shared@example.com")
    await sign_in.execute(original)
    newcomer = an_identity(email="shared@example.com")

    with pytest.raises(SsoSignInRefusedError):
        await sign_in.execute(newcomer)

    assert await identities.find_user_id(newcomer.provider, newcomer.subject) is None


async def test_the_same_person_may_link_one_identity_per_provider(
    sign_in: SignInWithIdentity,
) -> None:
    google = an_identity(provider="google", email="ada@example.com")
    other = an_identity(provider="other", email="ada@example.com")

    assert await sign_in.execute(google) == await sign_in.execute(other)


@pytest.mark.parametrize("email", ["not-an-email", "", "a@b", "nul\x00@example.com"])
async def test_an_address_the_domain_cannot_store_is_a_rejected_identity(
    sign_in: SignInWithIdentity, email: str
) -> None:
    with pytest.raises(IdentityCodeRejectedError):
        await sign_in.execute(an_identity(email=email))


@pytest.mark.parametrize(
    ("full_name", "expected"),
    [
        (None, "ada"),
        ("   ", "ada"),
        ("Ada\x00 Love\x1flace\x7f", "Ada Lovelace"),
        ("x" * 500, "x" * 200),
    ],
)
async def test_the_display_name_is_made_storable_and_falls_back_to_the_mailbox_name(
    sign_in: SignInWithIdentity, full_name: str | None, expected: str
) -> None:
    user = await sign_in.execute(an_identity(email="ada@example.com", full_name=full_name))

    assert user.full_name == expected


class _RacingUsers(InMemoryUserRepository):
    """Another request registers the same email between the lookup and the insert."""

    def __init__(self, winner: User) -> None:
        super().__init__()
        self._winner = winner
        self._raced = False

    async def add(self, user: User) -> None:
        if not self._raced:
            self._raced = True
            await super().add(self._winner)
            raise EmailAlreadyRegisteredError(user.email)
        await super().add(user)


async def test_losing_the_race_to_create_the_user_links_to_the_winner(
    identities: InMemoryUserIdentityRepository,
) -> None:
    winner = a_user()
    sign_in = SignInWithIdentity(_RacingUsers(winner), identities, clock=lambda: NOW)
    identity = an_identity(email=winner.email)

    user = await sign_in.execute(identity)

    assert user == winner
    assert await identities.find_user_id(identity.provider, identity.subject) == winner.id


class _RacingIdentities(InMemoryUserIdentityRepository):
    """A concurrent sign-in of the same identity links it first."""

    async def link(
        self, user_id: uuid.UUID, provider: str, subject: str, *, linked_at: datetime
    ) -> None:
        if await self.find_user_id(provider, subject) is None:
            await super().link(user_id, provider, subject, linked_at=linked_at)
        await super().link(user_id, provider, subject, linked_at=linked_at)


async def test_losing_the_race_to_link_the_identity_signs_in_as_the_linked_user(
    users: InMemoryUserRepository,
) -> None:
    existing = a_user()
    await users.add(existing)
    sign_in = SignInWithIdentity(users, _RacingIdentities(), clock=lambda: NOW)

    assert await sign_in.execute(an_identity(email=existing.email)) == existing
