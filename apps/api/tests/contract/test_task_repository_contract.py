"""Contract every TaskRepository adapter must honour.

The in-memory fake the unit and API tests rely on runs here next to the real adapters,
so a use case tested against the fake behaves the same against PostgreSQL.
Registering a new adapter = one new entry in ``ADAPTERS`` and one branch in ``store``.

Tasks point at users (``created_by``, ``assignee_id``), so every adapter is paired with the
user repository that writes to the store it references.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.errors import InvalidAssigneeError, TaskNotFound
from app.application.ports.task_repository import TaskRepository
from app.application.ports.user_repository import UserRepository
from app.domain.task import Task, TaskStatus
from app.infrastructure.db.engine import create_engine
from app.infrastructure.db.repositories.task import SqlAlchemyTaskRepository
from app.infrastructure.db.repositories.user import SqlAlchemyUserRepository
from tests.auth_fakes import InMemoryUserRepository, a_user
from tests.fakes import InMemoryTaskRepository

ADAPTERS = [
    pytest.param("in-memory"),
    pytest.param("sqlalchemy-postgresql", marks=pytest.mark.integration),
]

# PostgreSQL keeps microseconds, so this value survives a round trip unchanged.
CREATED = datetime(2026, 1, 5, 9, 0, 0, 123456, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Store:
    tasks: TaskRepository
    users: UserRepository


@pytest.fixture(params=ADAPTERS)
async def store(request: pytest.FixtureRequest) -> AsyncIterator[Store]:
    if request.param == "in-memory":
        users = InMemoryUserRepository()
        yield Store(InMemoryTaskRepository(users), users)
        return

    # Real PostgreSQL, migrated by Alembic; every test runs in a transaction that is
    # rolled back, so the cases stay independent of each other.
    engine = create_engine(request.getfixturevalue("migrated_database_url"))
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        ) as session:
            yield Store(SqlAlchemyTaskRepository(session), SqlAlchemyUserRepository(session))
        await transaction.rollback()
    await engine.dispose()


@pytest.fixture
def repository(store: Store) -> TaskRepository:
    return store.tasks


@pytest.fixture
async def creator(store: Store) -> uuid.UUID:
    return await stored_user(store)


async def stored_user(store: Store, *, is_active: bool = True) -> uuid.UUID:
    user = a_user(is_active=is_active)
    await store.users.add(user)
    return user.id


def a_task(
    created_by: uuid.UUID, *, title: str = "Write the report", created_at: datetime = CREATED
) -> Task:
    return Task.create(task_id=uuid.uuid4(), title=title, created_by=created_by, now=created_at)


async def test_get_of_an_unknown_id_returns_none(repository: TaskRepository) -> None:
    assert await repository.get(uuid.uuid4()) is None


async def test_an_added_task_is_returned_with_every_field_intact(
    store: Store, repository: TaskRepository, creator: uuid.UUID
) -> None:
    task = Task.create(
        task_id=uuid.uuid4(),
        title="Write the report",
        description="Q1 numbers",
        due_date=date(2026, 2, 1),
        created_by=creator,
        assignee_id=await stored_user(store),
        now=CREATED,
    )
    task.move_to(TaskStatus.DONE, now=CREATED + timedelta(hours=2))

    await repository.add(task)

    assert await repository.get(task.id) == task


async def test_a_minimal_task_round_trips_its_empty_fields(
    repository: TaskRepository, creator: uuid.UUID
) -> None:
    task = a_task(creator)

    await repository.add(task)

    stored = await repository.get(task.id)
    assert stored == task
    assert stored is not None
    assert stored.created_at.utcoffset() == timedelta(0)


async def test_get_for_update_of_an_unknown_id_returns_none(repository: TaskRepository) -> None:
    assert await repository.get_for_update(uuid.uuid4()) is None


async def test_get_for_update_returns_the_stored_task(
    repository: TaskRepository, creator: uuid.UUID
) -> None:
    task = a_task(creator)
    await repository.add(task)

    assert await repository.get_for_update(task.id) == task


async def test_a_task_loaded_for_update_is_stored_only_by_update(
    repository: TaskRepository, creator: uuid.UUID
) -> None:
    task = a_task(creator)
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


async def test_list_returns_every_task_newest_first(
    repository: TaskRepository, creator: uuid.UUID
) -> None:
    oldest = a_task(creator, title="oldest", created_at=CREATED)
    middle = a_task(creator, title="middle", created_at=CREATED + timedelta(minutes=1))
    newest = a_task(creator, title="newest", created_at=CREATED + timedelta(minutes=2))
    for task in (middle, newest, oldest):
        await repository.add(task)

    assert list(await repository.list()) == [newest, middle, oldest]


async def test_update_persists_the_new_state(
    store: Store, repository: TaskRepository, creator: uuid.UUID
) -> None:
    task = a_task(creator)
    await repository.add(task)
    later = CREATED + timedelta(days=1)
    assignee = await stored_user(store)

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


async def test_changes_are_not_stored_until_update_is_called(
    repository: TaskRepository, creator: uuid.UUID
) -> None:
    task = a_task(creator)
    await repository.add(task)

    task.retitle("Changed in memory only", now=CREATED + timedelta(days=1))

    stored = await repository.get(task.id)
    assert stored is not None
    assert stored.title == "Write the report"


async def test_update_of_an_unknown_task_raises_task_not_found(
    repository: TaskRepository, creator: uuid.UUID
) -> None:
    ghost = a_task(creator)

    with pytest.raises(TaskNotFound) as error:
        await repository.update(ghost)

    assert error.value.task_id == ghost.id


async def test_delete_removes_only_that_task(
    repository: TaskRepository, creator: uuid.UUID
) -> None:
    doomed, kept = a_task(creator, title="doomed"), a_task(creator, title="kept")
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


# --- tasks reference users -----------------------------------------------------------------
# The use cases ask a UserDirectory first; this is the backstop for whoever gets past it.


async def test_add_refuses_an_assignee_who_is_not_a_stored_user_and_stays_usable(
    repository: TaskRepository, creator: uuid.UUID
) -> None:
    nobody = uuid.uuid4()
    task = Task.create(
        task_id=uuid.uuid4(), title="t", created_by=creator, assignee_id=nobody, now=CREATED
    )

    with pytest.raises(InvalidAssigneeError) as error:
        await repository.add(task)

    assert error.value.assignee_id == nobody
    assert await repository.get(task.id) is None
    kept = a_task(creator)
    await repository.add(kept)
    assert await repository.get(kept.id) == kept


async def test_update_refuses_an_assignee_who_is_not_a_stored_user_and_keeps_the_stored_task(
    repository: TaskRepository, creator: uuid.UUID
) -> None:
    task = a_task(creator)
    await repository.add(task)
    nobody = uuid.uuid4()

    changed = await repository.get_for_update(task.id)
    assert changed is not None
    changed.assign_to(nobody, now=CREATED + timedelta(days=1))
    with pytest.raises(InvalidAssigneeError) as error:
        await repository.update(changed)

    assert error.value.assignee_id == nobody
    assert await repository.get(task.id) == task


async def test_an_inactive_user_can_stay_the_assignee_of_a_stored_task(
    store: Store, repository: TaskRepository, creator: uuid.UUID
) -> None:
    """Whether an assignee is still active is the directory's question, not the store's."""
    left_the_team = await stored_user(store, is_active=False)
    task = Task.create(
        task_id=uuid.uuid4(), title="t", created_by=creator, assignee_id=left_the_team, now=CREATED
    )

    await repository.add(task)

    assert await repository.get(task.id) == task
