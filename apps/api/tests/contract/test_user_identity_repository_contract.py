"""Contract every UserIdentityRepository adapter must honour (Liskov).

The in-memory fake runs everywhere; the SQLAlchemy adapter runs the same cases under the
``integration`` marker against a freshly migrated PostgreSQL database. Identities
reference users, so every case stores its users first.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from app.application.ports.user_identity_repository import UserIdentityRepository
from app.infrastructure.db.repositories.user_identity import SqlAlchemyUserIdentityRepository
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.errors import IdentityAlreadyLinkedError
from app.application.ports.user_repository import UserRepository
from app.infrastructure.db.engine import create_engine
from app.infrastructure.db.repositories.user import SqlAlchemyUserRepository
from tests.auth_fakes import InMemoryUserRepository, a_user
from tests.sso_fakes import InMemoryUserIdentityRepository

ADAPTERS = [
    pytest.param("in-memory"),
    pytest.param("sqlalchemy-postgresql", marks=pytest.mark.integration),
]
NOW = datetime(2026, 9, 18, 12, 30, tzinfo=UTC)


@dataclass(frozen=True)
class Repositories:
    identities: UserIdentityRepository
    users: UserRepository

    async def a_stored_user(self) -> uuid.UUID:
        user = a_user()
        await self.users.add(user)
        return user.id


@pytest.fixture(params=ADAPTERS)
async def repositories(request: pytest.FixtureRequest) -> AsyncIterator[Repositories]:
    if request.param == "in-memory":
        yield Repositories(InMemoryUserIdentityRepository(), InMemoryUserRepository())
        return

    engine = create_engine(request.getfixturevalue("migrated_database_url"))
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        ) as session:
            yield Repositories(
                SqlAlchemyUserIdentityRepository(session), SqlAlchemyUserRepository(session)
            )
        await transaction.rollback()
    await engine.dispose()


def a_subject() -> str:
    return f"subject-{uuid.uuid4().hex}"


async def test_a_linked_identity_is_found_by_provider_and_subject(
    repositories: Repositories,
) -> None:
    user_id, subject = await repositories.a_stored_user(), a_subject()

    await repositories.identities.link(user_id, "google", subject, linked_at=NOW)

    assert await repositories.identities.find_user_id("google", subject) == user_id


async def test_an_unknown_identity_is_none(repositories: Repositories) -> None:
    assert await repositories.identities.find_user_id("google", a_subject()) is None


async def test_the_same_subject_at_another_provider_is_another_identity(
    repositories: Repositories,
) -> None:
    first, second, subject = (
        await repositories.a_stored_user(),
        await repositories.a_stored_user(),
        a_subject(),
    )

    await repositories.identities.link(first, "google", subject, linked_at=NOW)
    await repositories.identities.link(second, "other", subject, linked_at=NOW)

    assert await repositories.identities.find_user_id("google", subject) == first
    assert await repositories.identities.find_user_id("other", subject) == second


async def test_an_identity_belongs_to_one_user_only(repositories: Repositories) -> None:
    owner, thief, subject = (
        await repositories.a_stored_user(),
        await repositories.a_stored_user(),
        a_subject(),
    )
    await repositories.identities.link(owner, "google", subject, linked_at=NOW)

    with pytest.raises(IdentityAlreadyLinkedError):
        await repositories.identities.link(thief, "google", subject, linked_at=NOW)

    assert await repositories.identities.find_user_id("google", subject) == owner


async def test_a_user_has_at_most_one_identity_per_provider(repositories: Repositories) -> None:
    user_id, first, second = await repositories.a_stored_user(), a_subject(), a_subject()
    await repositories.identities.link(user_id, "google", first, linked_at=NOW)

    with pytest.raises(IdentityAlreadyLinkedError):
        await repositories.identities.link(user_id, "google", second, linked_at=NOW)

    assert await repositories.identities.find_user_id("google", second) is None


async def test_a_user_may_have_one_identity_at_each_provider(repositories: Repositories) -> None:
    user_id, subject = await repositories.a_stored_user(), a_subject()

    await repositories.identities.link(user_id, "google", subject, linked_at=NOW)
    await repositories.identities.link(user_id, "other", subject, linked_at=NOW)

    assert await repositories.identities.find_user_id("other", subject) == user_id


async def test_the_repository_stays_usable_after_a_rejected_link(
    repositories: Repositories,
) -> None:
    owner, other, subject = (
        await repositories.a_stored_user(),
        await repositories.a_stored_user(),
        a_subject(),
    )
    await repositories.identities.link(owner, "google", subject, linked_at=NOW)
    with pytest.raises(IdentityAlreadyLinkedError):
        await repositories.identities.link(other, "google", subject, linked_at=NOW)

    another = a_subject()
    await repositories.identities.link(other, "google", another, linked_at=NOW)

    assert await repositories.identities.find_user_id("google", another) == other
