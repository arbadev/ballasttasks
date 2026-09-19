"""The one place that commits or rolls back, against real PostgreSQL."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.task import Task
from app.infrastructure.db.engine import create_engine
from app.infrastructure.db.repositories.task import SqlAlchemyTaskRepository
from app.infrastructure.db.session import create_session_factory
from app.infrastructure.db.unit_of_work import transactional_session
from tests import builders
from tests.postgres import INSERT_USER, user_row

pytestmark = pytest.mark.integration

SessionFactory = async_sessionmaker[AsyncSession]


@pytest.fixture
async def session_factory(migrated_database_url: str) -> AsyncIterator[SessionFactory]:
    engine = create_engine(migrated_database_url)
    yield create_session_factory(engine)
    await engine.dispose()


@pytest.fixture
async def creator(session_factory: SessionFactory) -> uuid.UUID:
    """Tasks reference users, so somebody has to have created them."""
    user = user_row()
    async with transactional_session(session_factory) as session:
        await session.execute(INSERT_USER, user)
    return user["id"]


def a_task(created_by: uuid.UUID) -> Task:
    # The shared database keeps what other modules committed, so the key must be one of a kind.
    return builders.a_task(
        created_by, key=f"UW-{uuid.uuid4().int % 900_000_000 + 1}", now=datetime.now(UTC)
    )


async def test_work_is_committed_when_the_block_succeeds(
    session_factory: SessionFactory, creator: uuid.UUID
) -> None:
    task = a_task(creator)

    async with transactional_session(session_factory) as session:
        await SqlAlchemyTaskRepository(session).add(task)

    async with transactional_session(session_factory) as session:
        repository = SqlAlchemyTaskRepository(session)
        assert await repository.get(task.id) == task
        await repository.delete(task.id)  # leave the shared test database as it was

    async with transactional_session(session_factory) as session:
        assert await SqlAlchemyTaskRepository(session).get(task.id) is None


async def test_work_is_rolled_back_when_the_block_raises(
    session_factory: SessionFactory, creator: uuid.UUID
) -> None:
    task = a_task(creator)

    async def add_then_fail() -> None:
        async with transactional_session(session_factory) as session:
            await SqlAlchemyTaskRepository(session).add(task)
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await add_then_fail()

    async with transactional_session(session_factory) as session:
        assert await SqlAlchemyTaskRepository(session).get(task.id) is None
