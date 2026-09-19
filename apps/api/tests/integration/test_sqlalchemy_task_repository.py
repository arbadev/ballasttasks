"""What only the PostgreSQL adapter can show: row locks, and rows the domain rejects."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import sqlalchemy
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.errors import StoredTaskInvalid
from app.application.use_cases.update_task import TaskChanges, UpdateTask
from app.domain.task import Task, TaskStatus
from app.infrastructure.db.engine import create_engine
from app.infrastructure.db.repositories.task import SqlAlchemyTaskRepository
from app.infrastructure.db.session import create_session_factory
from app.infrastructure.db.unit_of_work import transactional_session

pytestmark = pytest.mark.integration

SessionFactory = async_sessionmaker[AsyncSession]

LOCK_WAITERS = sqlalchemy.text(
    "SELECT count(*) FROM pg_stat_activity "
    "WHERE datname = current_database() AND wait_event_type = 'Lock'"
)


@pytest.fixture
async def session_factory(migrated_database_url: str) -> AsyncIterator[SessionFactory]:
    engine = create_engine(migrated_database_url)
    yield create_session_factory(engine)
    await engine.dispose()


async def until_a_writer_waits_for_a_lock(session_factory: SessionFactory) -> None:
    while True:
        async with session_factory() as session:
            if await session.scalar(LOCK_WAITERS):
                return
        await asyncio.sleep(0.05)


async def test_a_second_writer_waits_and_then_works_from_what_the_first_one_stored(
    session_factory: SessionFactory,
) -> None:
    """Two PATCHes that both read ``todo``: ``done`` first, ``in_progress`` right behind it."""
    task = Task.create(
        task_id=uuid.uuid4(),
        title="Write the report",
        created_by=uuid.uuid4(),
        now=datetime.now(UTC),
    )
    async with transactional_session(session_factory) as session:
        await SqlAlchemyTaskRepository(session).add(task)
    first_has_written = asyncio.Event()
    first_may_commit = asyncio.Event()

    async def first_writer() -> None:
        async with transactional_session(session_factory) as session:
            await UpdateTask(SqlAlchemyTaskRepository(session)).execute(
                task.id, TaskChanges(status=TaskStatus.DONE)
            )
            first_has_written.set()
            await first_may_commit.wait()

    async def second_writer() -> None:
        async with transactional_session(session_factory) as session:
            await UpdateTask(SqlAlchemyTaskRepository(session)).execute(
                task.id, TaskChanges(status=TaskStatus.IN_PROGRESS)
            )

    try:
        async with asyncio.timeout(30):
            first = asyncio.create_task(first_writer())
            await first_has_written.wait()
            second = asyncio.create_task(second_writer())
            await until_a_writer_waits_for_a_lock(session_factory)
            first_may_commit.set()
            await asyncio.gather(first, second)

        async with transactional_session(session_factory) as session:
            stored = await SqlAlchemyTaskRepository(session).get(task.id)
        assert stored is not None
        assert stored.status is TaskStatus.IN_PROGRESS
        assert stored.completed_at is None
    finally:
        first_may_commit.set()
        async with transactional_session(session_factory) as session:
            await session.execute(
                sqlalchemy.text("DELETE FROM tasks WHERE id = :id"), {"id": task.id}
            )


async def test_a_stored_row_the_domain_rejects_is_reported_as_stored_task_invalid(
    session_factory: SessionFactory,
) -> None:
    task_id = uuid.uuid4()
    blank_title_row = sqlalchemy.text(
        "INSERT INTO tasks (id, title, status, created_by, created_at, updated_at) "
        "VALUES (:id, '   ', 'todo', gen_random_uuid(), now(), now())"
    )

    async with session_factory() as session:
        await session.execute(blank_title_row, {"id": task_id})
        repository = SqlAlchemyTaskRepository(session)

        with pytest.raises(StoredTaskInvalid) as error:
            await repository.get(task_id)
        with pytest.raises(StoredTaskInvalid):
            await repository.list()
        await session.rollback()

    assert error.value.task_id == task_id
