"""What only real PostgreSQL can prove about the user adapter: it joins the shared unit of
work, and the unique constraint settles a race between two transactions."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.errors import EmailAlreadyRegisteredError
from app.domain.user import User
from app.infrastructure.db.engine import create_engine
from app.infrastructure.db.repositories.user import SqlAlchemyUserRepository
from app.infrastructure.db.session import create_session_factory
from app.infrastructure.db.unit_of_work import transactional_session

pytestmark = pytest.mark.integration


@pytest.fixture
async def session_factory(
    migrated_database_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(migrated_database_url)
    yield create_session_factory(engine)
    await engine.dispose()


def a_user(email: str) -> User:
    return User(
        id=uuid.uuid4(),
        email=email,
        full_name="Ada Lovelace",
        hashed_password="$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA",
        is_active=True,
        created_at=datetime(2026, 9, 18, 12, 30, tzinfo=UTC),
    )


async def test_the_repository_never_commits_on_its_own(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user = a_user(f"{uuid.uuid4().hex}@example.com")

    async def add_then_fail() -> None:
        async with transactional_session(session_factory) as session:
            await SqlAlchemyUserRepository(session).add(user)
            raise RuntimeError("abandon the unit of work")

    with pytest.raises(RuntimeError, match="abandon"):
        await add_then_fail()

    async with transactional_session(session_factory) as session:
        assert await SqlAlchemyUserRepository(session).get_by_id(user.id) is None


async def test_a_committed_unit_of_work_is_visible_to_the_next_one(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user = a_user(f"{uuid.uuid4().hex}@example.com")

    async with transactional_session(session_factory) as session:
        await SqlAlchemyUserRepository(session).add(user)

    async with transactional_session(session_factory) as session:
        assert await SqlAlchemyUserRepository(session).get_by_email(user.email) == user


async def test_a_rejected_add_leaves_the_rest_of_the_unit_of_work_intact(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    taken = a_user(f"{uuid.uuid4().hex}@example.com")
    other = a_user(f"{uuid.uuid4().hex}@example.com")
    async with transactional_session(session_factory) as session:
        await SqlAlchemyUserRepository(session).add(taken)

    async with transactional_session(session_factory) as session:
        users = SqlAlchemyUserRepository(session)
        await users.add(other)
        with pytest.raises(EmailAlreadyRegisteredError):
            await users.add(a_user(taken.email))

    async with transactional_session(session_factory) as session:
        assert await SqlAlchemyUserRepository(session).get_by_id(other.id) == other


async def test_concurrent_transactions_adding_one_email_let_exactly_one_through(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    email = f"{uuid.uuid4().hex}@example.com"
    contenders = [a_user(email) for _ in range(8)]

    async def register(user: User) -> None:
        async with transactional_session(session_factory) as session:
            await SqlAlchemyUserRepository(session).add(user)

    outcomes = await asyncio.gather(*(register(u) for u in contenders), return_exceptions=True)

    assert sum(outcome is None for outcome in outcomes) == 1
    assert sum(isinstance(outcome, EmailAlreadyRegisteredError) for outcome in outcomes) == 7
    async with transactional_session(session_factory) as session:
        assert await SqlAlchemyUserRepository(session).get_by_email(email) in contenders
