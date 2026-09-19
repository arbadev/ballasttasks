"""Contract every TaskRepository adapter must honour.

The in-memory fake the unit and API tests rely on runs here next to the real adapters,
so a use case tested against the fake behaves the same against PostgreSQL.
Registering a new adapter = one new entry in ``ADAPTERS`` and one branch in ``repository``.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.errors import TaskNotFound
from app.application.ports.task_repository import TaskRepository
from app.domain.task import Task, TaskStatus
from app.infrastructure.db.engine import create_engine
from app.infrastructure.db.repositories.task import SqlAlchemyTaskRepository
from tests.fakes import InMemoryTaskRepository

ADAPTERS = [
    pytest.param("in-memory"),
    pytest.param("sqlalchemy-postgresql", marks=pytest.mark.integration),
]

# PostgreSQL keeps microseconds, so this value survives a round trip unchanged.
CREATED = datetime(2026, 1, 5, 9, 0, 0, 123456, tzinfo=UTC)


@pytest.fixture(params=ADAPTERS)
async def repository(request: pytest.FixtureRequest) -> AsyncIterator[TaskRepository]:
    if request.param == "in-memory":
        yield InMemoryTaskRepository()
        return

    # Real PostgreSQL, migrated by Alembic; every test runs in a transaction that is
    # rolled back, so the cases stay independent of each other.
    engine = create_engine(request.getfixturevalue("migrated_database_url"))
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        ) as session:
            yield SqlAlchemyTaskRepository(session)
        await transaction.rollback()
    await engine.dispose()


def a_task(*, title: str = "Write the report", created_at: datetime = CREATED) -> Task:
    return Task.create(task_id=uuid.uuid4(), title=title, created_by=uuid.uuid4(), now=created_at)


async def test_get_of_an_unknown_id_returns_none(repository: TaskRepository) -> None:
    assert await repository.get(uuid.uuid4()) is None


async def test_an_added_task_is_returned_with_every_field_intact(
    repository: TaskRepository,
) -> None:
    task = Task.create(
        task_id=uuid.uuid4(),
        title="Write the report",
        description="Q1 numbers",
        due_date=date(2026, 2, 1),
        created_by=uuid.uuid4(),
        assignee_id=uuid.uuid4(),
        now=CREATED,
    )
    task.move_to(TaskStatus.DONE, now=CREATED + timedelta(hours=2))

    await repository.add(task)

    assert await repository.get(task.id) == task


async def test_a_minimal_task_round_trips_its_empty_fields(repository: TaskRepository) -> None:
    task = a_task()

    await repository.add(task)

    stored = await repository.get(task.id)
    assert stored == task
    assert stored is not None
    assert stored.created_at.utcoffset() == timedelta(0)


async def test_get_for_update_of_an_unknown_id_returns_none(repository: TaskRepository) -> None:
    assert await repository.get_for_update(uuid.uuid4()) is None


async def test_get_for_update_returns_the_stored_task(repository: TaskRepository) -> None:
    task = a_task()
    await repository.add(task)

    assert await repository.get_for_update(task.id) == task


async def test_a_task_loaded_for_update_is_stored_only_by_update(
    repository: TaskRepository,
) -> None:
    task = a_task()
    await repository.add(task)
    later = CREATED + timedelta(days=1)

    loaded = await repository.get_for_update(task.id)
    assert loaded is not None
    loaded.move_to(TaskStatus.DONE, now=later)
    assert await repository.get(task.id) == task

    await repository.update(loaded)
    assert await repository.get(task.id) == loaded


async def test_list_is_empty_when_nothing_was_added(repository: TaskRepository) -> None:
    assert list(await repository.list()) == []


async def test_list_returns_every_task_newest_first(repository: TaskRepository) -> None:
    oldest = a_task(title="oldest", created_at=CREATED)
    middle = a_task(title="middle", created_at=CREATED + timedelta(minutes=1))
    newest = a_task(title="newest", created_at=CREATED + timedelta(minutes=2))
    for task in (middle, newest, oldest):
        await repository.add(task)

    assert list(await repository.list()) == [newest, middle, oldest]


async def test_update_persists_the_new_state(repository: TaskRepository) -> None:
    task = a_task()
    await repository.add(task)
    later = CREATED + timedelta(days=1)
    assignee = uuid.uuid4()

    task.retitle("Publish the report", now=later)
    task.describe("Final numbers", now=later)
    task.reschedule(date(2026, 3, 1), now=later)
    task.assign_to(assignee, now=later)
    task.move_to(TaskStatus.DONE, now=later)
    await repository.update(task)

    stored = await repository.get(task.id)
    assert stored == task
    assert stored is not None
    assert stored.completed_at == later
    assert stored.created_at == CREATED


async def test_changes_are_not_stored_until_update_is_called(repository: TaskRepository) -> None:
    task = a_task()
    await repository.add(task)

    task.retitle("Changed in memory only", now=CREATED + timedelta(days=1))

    stored = await repository.get(task.id)
    assert stored is not None
    assert stored.title == "Write the report"


async def test_update_of_an_unknown_task_raises_task_not_found(
    repository: TaskRepository,
) -> None:
    ghost = a_task()

    with pytest.raises(TaskNotFound) as error:
        await repository.update(ghost)

    assert error.value.task_id == ghost.id


async def test_delete_removes_only_that_task(repository: TaskRepository) -> None:
    doomed, kept = a_task(title="doomed"), a_task(title="kept")
    await repository.add(doomed)
    await repository.add(kept)

    await repository.delete(doomed.id)

    assert await repository.get(doomed.id) is None
    assert list(await repository.list()) == [kept]


async def test_delete_of_an_unknown_task_raises_task_not_found(
    repository: TaskRepository,
) -> None:
    task_id = uuid.uuid4()

    with pytest.raises(TaskNotFound) as error:
        await repository.delete(task_id)

    assert error.value.task_id == task_id
