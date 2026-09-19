"""Task keys under concurrency, against real PostgreSQL: no duplicates, no gaps, no races.

The counter lives on the project row and is taken with ``UPDATE ... RETURNING`` inside the
unit of work, so a second creator waits for the first one's commit or rollback.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.use_cases.create_task import CreateTask
from app.domain.project import DEFAULT_PROJECT_ID
from app.domain.task import Task
from app.domain.task_key import TaskKey
from app.infrastructure.db.engine import create_engine
from app.infrastructure.db.repositories.activity import SqlAlchemyActivityLog
from app.infrastructure.db.repositories.project import SqlAlchemyProjectRepository
from app.infrastructure.db.repositories.task import SqlAlchemyTaskRepository
from app.infrastructure.db.repositories.user_directory import SqlAlchemyUserDirectory
from app.infrastructure.db.session import create_session_factory
from app.infrastructure.db.unit_of_work import transactional_session
from tests.builders import a_project
from tests.postgres import INSERT_USER, run_alembic, temporary_database, user_row

pytestmark = pytest.mark.integration

SessionFactory = async_sessionmaker[AsyncSession]
CREATORS = 12


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with temporary_database() as url:
        run_alembic(url, "upgrade", "head")
        yield url


@pytest.fixture
async def session_factory(database_url: str) -> AsyncIterator[SessionFactory]:
    engine = create_engine(database_url)
    yield create_session_factory(engine)
    await engine.dispose()


@pytest.fixture
async def creator(session_factory: SessionFactory) -> uuid.UUID:
    user = user_row()
    async with transactional_session(session_factory) as session:
        await session.execute(INSERT_USER, user)
    return user["id"]


async def create_task(
    session_factory: SessionFactory, creator: uuid.UUID, project_id: uuid.UUID, title: str
) -> Task:
    """One request: its own session, its own transaction."""
    async with transactional_session(session_factory) as session:
        return await CreateTask(
            SqlAlchemyTaskRepository(session),
            SqlAlchemyUserDirectory(session),
            SqlAlchemyProjectRepository(session),
            SqlAlchemyActivityLog(session),
        ).execute(title=title, created_by=creator, project_id=project_id)


async def test_concurrent_creators_get_consecutive_keys_without_duplicates_or_gaps(
    session_factory: SessionFactory, creator: uuid.UUID
) -> None:
    project = a_project(name="Concurrent", key="CC")
    async with transactional_session(session_factory) as session:
        await SqlAlchemyProjectRepository(session).add(project)

    async with asyncio.timeout(60):
        tasks = await asyncio.gather(
            *(
                create_task(session_factory, creator, project.id, f"task {n}")
                for n in range(CREATORS)
            )
        )

    assert sorted(task.key for task in tasks) == [f"CC-{n:02d}" for n in range(1, CREATORS + 1)]
    async with transactional_session(session_factory) as session:
        assert await SqlAlchemyProjectRepository(session).allocate_task_key(project.id) == TaskKey(
            "CC", CREATORS + 1
        )
        await session.rollback()


async def test_a_creation_that_rolls_back_gives_its_number_back(
    session_factory: SessionFactory, creator: uuid.UUID
) -> None:
    project = a_project(name="Rollback", key="RB")
    async with transactional_session(session_factory) as session:
        await SqlAlchemyProjectRepository(session).add(project)
    first = await create_task(session_factory, creator, project.id, "kept")

    abandoned: list[Task] = []

    async def a_request_that_fails_after_creating_a_task() -> None:
        async with transactional_session(session_factory) as session:
            abandoned.append(
                await CreateTask(
                    SqlAlchemyTaskRepository(session),
                    SqlAlchemyUserDirectory(session),
                    SqlAlchemyProjectRepository(session),
                    SqlAlchemyActivityLog(session),
                ).execute(title="abandoned", created_by=creator, project_id=project.id)
            )
            raise RuntimeError("something failed later in the request")

    with pytest.raises(RuntimeError, match="later in the request"):
        await a_request_that_fails_after_creating_a_task()
    second = await create_task(session_factory, creator, project.id, "kept too")

    assert (first.key, abandoned[0].key, second.key) == ("RB-01", "RB-02", "RB-02")


async def test_projects_do_not_wait_for_each_other(
    session_factory: SessionFactory, creator: uuid.UUID
) -> None:
    """The lock is one project's row: a creator in the Inbox is not held up by an open
    transaction that took a key in another project."""
    project = a_project(name="Held", key="HE")
    async with transactional_session(session_factory) as session:
        await SqlAlchemyProjectRepository(session).add(project)

    async with transactional_session(session_factory) as holding:
        await SqlAlchemyProjectRepository(holding).allocate_task_key(project.id)
        async with asyncio.timeout(10):
            inbox_task = await create_task(session_factory, creator, DEFAULT_PROJECT_ID, "free")
        await holding.rollback()

    assert inbox_task.key.startswith("IN-")
