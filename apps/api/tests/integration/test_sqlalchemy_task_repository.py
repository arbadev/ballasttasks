"""What only the PostgreSQL adapter can show: row locks, rows the domain rejects, and the
foreign key settling what a check-then-write cannot."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime

import pytest
import sqlalchemy
from app.infrastructure.db.repositories.project import SqlAlchemyProjectRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.errors import InvalidAssigneeError, StoredTaskInvalid
from app.application.task_query import TaskQuery
from app.application.use_cases.create_task import CreateTask
from app.application.use_cases.update_task import TaskChanges, UpdateTask
from app.domain.task import Task, TaskStatus
from app.infrastructure.db.engine import create_engine
from app.infrastructure.db.repositories.task import SqlAlchemyTaskRepository
from app.infrastructure.db.repositories.user_directory import SqlAlchemyUserDirectory
from app.infrastructure.db.session import create_session_factory
from app.infrastructure.db.unit_of_work import transactional_session
from tests import builders
from tests.postgres import INSERT_USER, TASK_PROJECT_COLUMNS, TASK_PROJECT_VALUES, user_row

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


@pytest.fixture
async def creator(session_factory: SessionFactory) -> uuid.UUID:
    """Tasks reference users, so somebody has to have created them."""
    return await stored_user(session_factory)


def a_task(created_by: uuid.UUID, **details: object) -> Task:
    # The shared database keeps what other modules committed, so the key must be one of a kind.
    key = f"TR-{uuid.uuid4().int % 900_000_000 + 1}"
    return builders.a_task(created_by, key=key, now=datetime.now(UTC), **details)


async def stored_user(session_factory: SessionFactory, *, is_active: bool = True) -> uuid.UUID:
    user = user_row(is_active=is_active)
    async with transactional_session(session_factory) as session:
        await session.execute(INSERT_USER, user)
    return user["id"]


async def until_a_writer_waits_for_a_lock(session_factory: SessionFactory) -> None:
    while True:
        async with session_factory() as session:
            if await session.scalar(LOCK_WAITERS):
                return
        await asyncio.sleep(0.05)


async def test_a_second_writer_waits_and_then_works_from_what_the_first_one_stored(
    session_factory: SessionFactory, creator: uuid.UUID
) -> None:
    """Two PATCHes that both read ``todo``: ``done`` first, ``in_progress`` right behind it."""
    task = a_task(creator)
    async with transactional_session(session_factory) as session:
        await SqlAlchemyTaskRepository(session).add(task)
    first_has_written = asyncio.Event()
    first_may_commit = asyncio.Event()

    async def first_writer() -> None:
        async with transactional_session(session_factory) as session:
            await UpdateTask(
                SqlAlchemyTaskRepository(session),
                SqlAlchemyUserDirectory(session),
                SqlAlchemyProjectRepository(session),
            ).execute(task.id, TaskChanges(status=TaskStatus.DONE))
            first_has_written.set()
            await first_may_commit.wait()

    async def second_writer() -> None:
        async with transactional_session(session_factory) as session:
            await UpdateTask(
                SqlAlchemyTaskRepository(session),
                SqlAlchemyUserDirectory(session),
                SqlAlchemyProjectRepository(session),
            ).execute(task.id, TaskChanges(status=TaskStatus.IN_PROGRESS))

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
    session_factory: SessionFactory, creator: uuid.UUID
) -> None:
    task_id = uuid.uuid4()
    blank_title_row = sqlalchemy.text(
        "INSERT INTO tasks (id, title, status, created_by, created_at, updated_at, "
        f"{TASK_PROJECT_COLUMNS}) "
        f"VALUES (:id, '   ', 'todo', :created_by, now(), now(), {TASK_PROJECT_VALUES})"
    )

    async with session_factory() as session:
        await session.execute(blank_title_row, {"id": task_id, "created_by": creator})
        repository = SqlAlchemyTaskRepository(session)

        with pytest.raises(StoredTaskInvalid) as error:
            await repository.get(task_id)
        with pytest.raises(StoredTaskInvalid):
            await repository.search(TaskQuery(), today=date(2026, 1, 5))
        await session.rollback()

    assert error.value.task_id == task_id


async def test_a_refused_assignee_leaves_the_rest_of_the_unit_of_work_intact(
    session_factory: SessionFactory, creator: uuid.UUID
) -> None:
    kept = a_task(creator, title="kept")
    refused = a_task(creator, title="refused", assignee_id=uuid.uuid4())

    async with transactional_session(session_factory) as session:
        repository = SqlAlchemyTaskRepository(session)
        await repository.add(kept)
        with pytest.raises(InvalidAssigneeError):
            await repository.add(refused)

    async with transactional_session(session_factory) as session:
        repository = SqlAlchemyTaskRepository(session)
        assert await repository.get(kept.id) == kept
        assert await repository.get(refused.id) is None


async def test_an_assignee_deleted_between_the_check_and_the_write_is_refused_by_the_foreign_key(
    session_factory: SessionFactory, creator: uuid.UUID
) -> None:
    """The race the directory check alone cannot win: the user is there when ``CreateTask``
    asks, and gone by the time the task is written."""
    assignee = await stored_user(session_factory)

    class DirectoryThatLosesTheRace:
        def __init__(self, session: AsyncSession) -> None:
            self._directory = SqlAlchemyUserDirectory(session)

        async def is_active_user(self, user_id: uuid.UUID) -> bool:
            answer = await self._directory.is_active_user(user_id)
            async with transactional_session(session_factory) as elsewhere:
                await elsewhere.execute(
                    sqlalchemy.text("DELETE FROM users WHERE id = :id"), {"id": user_id}
                )
            return answer

    async def create() -> None:
        async with transactional_session(session_factory) as session:
            await CreateTask(
                SqlAlchemyTaskRepository(session),
                DirectoryThatLosesTheRace(session),
                SqlAlchemyProjectRepository(session),
            ).execute(title="Write the report", created_by=creator, assignee_id=assignee)

    with pytest.raises(InvalidAssigneeError) as error:
        await create()

    assert error.value.assignee_id == assignee
