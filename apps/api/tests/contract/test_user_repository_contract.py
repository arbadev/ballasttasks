"""Contract every UserRepository adapter must honour (Liskov).

The in-memory fake runs everywhere; the SQLAlchemy adapter runs the same cases under the
``integration`` marker against a freshly migrated PostgreSQL database. The race between
two transactions needs one session per contender, so it lives in
``tests/integration/test_sqlalchemy_user_repository.py``.
"""

import dataclasses
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.errors import EmailAlreadyRegisteredError
from app.application.ports.user_repository import UserRepository
from app.domain.user import User
from app.infrastructure.db.engine import create_engine
from app.infrastructure.db.repositories.user import SqlAlchemyUserRepository
from tests.auth_fakes import InMemoryUserRepository

ADAPTERS = [
    pytest.param("in-memory"),
    pytest.param("sqlalchemy-postgresql", marks=pytest.mark.integration),
]


@pytest.fixture(params=ADAPTERS)
async def users(request: pytest.FixtureRequest) -> AsyncIterator[UserRepository]:
    if request.param == "in-memory":
        yield InMemoryUserRepository()
        return

    # Real PostgreSQL, migrated by Alembic; every test runs in a transaction that is
    # rolled back, so the cases stay independent of each other.
    engine = create_engine(request.getfixturevalue("migrated_database_url"))
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        ) as session:
            yield SqlAlchemyUserRepository(session)
        await transaction.rollback()
    await engine.dispose()


def make_user(**overrides: object) -> User:
    fields: dict[str, object] = {
        "id": uuid.uuid4(),
        "email": f"{uuid.uuid4().hex}@example.com",
        "full_name": "Ada Lovelace",
        "hashed_password": "$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA",
        "is_active": True,
        "created_at": datetime(2026, 9, 18, 12, 30, 15, 123456, tzinfo=UTC),
    }
    return User(**{**fields, **overrides})  # type: ignore[arg-type]


async def test_an_added_user_is_found_by_id_and_by_email_with_every_field(
    users: UserRepository,
) -> None:
    user = make_user()

    await users.add(user)

    assert await users.get_by_id(user.id) == user
    assert await users.get_by_email(user.email) == user


async def test_an_inactive_user_round_trips_as_inactive(users: UserRepository) -> None:
    user = make_user(is_active=False)

    await users.add(user)

    found = await users.get_by_id(user.id)
    assert found is not None
    assert found.is_active is False


async def test_created_at_keeps_its_instant_and_stays_timezone_aware(
    users: UserRepository,
) -> None:
    user = make_user()
    await users.add(user)

    found = await users.get_by_id(user.id)

    assert found is not None
    assert found.created_at.tzinfo is not None
    assert found.created_at == user.created_at


async def test_unknown_id_and_unknown_email_are_none(users: UserRepository) -> None:
    assert await users.get_by_id(uuid.uuid4()) is None
    assert await users.get_by_email(f"{uuid.uuid4().hex}@example.com") is None


async def test_a_second_user_with_the_same_email_is_rejected_and_the_first_is_kept(
    users: UserRepository,
) -> None:
    first = make_user()
    await users.add(first)

    with pytest.raises(EmailAlreadyRegisteredError):
        await users.add(dataclasses.replace(first, id=uuid.uuid4(), full_name="Impostor"))

    assert await users.get_by_email(first.email) == first


async def test_the_repository_stays_usable_after_a_rejected_add(users: UserRepository) -> None:
    first = make_user()
    await users.add(first)
    with pytest.raises(EmailAlreadyRegisteredError):
        await users.add(dataclasses.replace(first, id=uuid.uuid4()))

    another = make_user()
    await users.add(another)

    assert await users.get_by_id(another.id) == another
