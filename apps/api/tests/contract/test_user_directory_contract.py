"""Contract every UserDirectory adapter must honour (Liskov).

The in-memory fake runs everywhere; the SQLAlchemy adapter runs the same cases under the
``integration`` marker against a freshly migrated PostgreSQL database. Each adapter is
paired with the user repository that writes to the store it reads.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.user_directory import UserDirectory
from app.application.ports.user_repository import UserRepository
from app.infrastructure.db.engine import create_engine
from app.infrastructure.db.repositories.user import SqlAlchemyUserRepository
from app.infrastructure.db.repositories.user_directory import SqlAlchemyUserDirectory
from tests.auth_fakes import InMemoryUserDirectory, InMemoryUserRepository, a_user

ADAPTERS = [
    pytest.param("in-memory"),
    pytest.param("sqlalchemy-postgresql", marks=pytest.mark.integration),
]


@dataclass(frozen=True, slots=True)
class Store:
    users: UserRepository
    directory: UserDirectory


@pytest.fixture(params=ADAPTERS)
async def store(request: pytest.FixtureRequest) -> AsyncIterator[Store]:
    if request.param == "in-memory":
        users = InMemoryUserRepository()
        yield Store(users, InMemoryUserDirectory(users))
        return

    # Real PostgreSQL, migrated by Alembic; every test runs in a transaction that is
    # rolled back, so the cases stay independent of each other.
    engine = create_engine(request.getfixturevalue("migrated_database_url"))
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        ) as session:
            yield Store(SqlAlchemyUserRepository(session), SqlAlchemyUserDirectory(session))
        await transaction.rollback()
    await engine.dispose()


async def test_a_stored_active_user_is_an_active_user(store: Store) -> None:
    user = a_user()
    await store.users.add(user)

    assert await store.directory.is_active_user(user.id) is True


async def test_a_stored_inactive_user_is_not_an_active_user(store: Store) -> None:
    user = a_user(is_active=False)
    await store.users.add(user)

    assert await store.directory.is_active_user(user.id) is False


async def test_an_id_nobody_has_is_not_an_active_user(store: Store) -> None:
    await store.users.add(a_user())

    assert await store.directory.is_active_user(uuid.uuid4()) is False


async def test_the_answer_is_about_that_user_only(store: Store) -> None:
    active, inactive = a_user(), a_user(is_active=False)
    await store.users.add(active)
    await store.users.add(inactive)

    assert await store.directory.is_active_user(active.id) is True
    assert await store.directory.is_active_user(inactive.id) is False
