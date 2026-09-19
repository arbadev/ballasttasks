"""Contract every AttachmentRepository adapter must honour.

The in-memory fake the unit and API tests rely on runs here next to the PostgreSQL adapter.
An attachment belongs to a task, so every adapter is paired with the task and user
repositories that write to the store it references.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta

import pytest
from app.application.ports.attachment_repository import AttachmentRepository
from app.domain.attachment import AttachmentKind
from app.infrastructure.db.repositories.attachment import SqlAlchemyAttachmentRepository
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.errors import AttachmentNotFound, TaskNotFound
from app.application.ports.task_repository import TaskRepository
from app.application.ports.user_repository import UserRepository
from app.domain.task import Task
from app.infrastructure.db.engine import create_engine
from app.infrastructure.db.repositories.task import SqlAlchemyTaskRepository
from app.infrastructure.db.repositories.user import SqlAlchemyUserRepository
from tests.auth_fakes import InMemoryUserRepository, a_user
from tests.builders import CREATED, a_file, a_link, a_task
from tests.fakes import (
    InMemoryAttachmentRepository,
    InMemoryProjectRepository,
    InMemoryTaskRepository,
)

ADAPTERS = [
    pytest.param("in-memory"),
    pytest.param("sqlalchemy-postgresql", marks=pytest.mark.integration),
]


@dataclass(frozen=True, slots=True)
class Store:
    attachments: AttachmentRepository
    tasks: TaskRepository
    users: UserRepository


@pytest.fixture(params=ADAPTERS)
async def store(request: pytest.FixtureRequest) -> AsyncIterator[Store]:
    if request.param == "in-memory":
        users = InMemoryUserRepository()
        tasks = InMemoryTaskRepository(users, InMemoryProjectRepository())
        yield Store(InMemoryAttachmentRepository(tasks), tasks, users)
        return

    # Real PostgreSQL, migrated by Alembic; every test runs in a transaction that is
    # rolled back, so the cases stay independent of each other.
    engine = create_engine(request.getfixturevalue("pristine_database_url"))
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        ) as session:
            yield Store(
                SqlAlchemyAttachmentRepository(session),
                SqlAlchemyTaskRepository(session),
                SqlAlchemyUserRepository(session),
            )
        await transaction.rollback()
    await engine.dispose()


@pytest.fixture
def repository(store: Store) -> AttachmentRepository:
    return store.attachments


@pytest.fixture
async def creator(store: Store) -> uuid.UUID:
    user = a_user()
    await store.users.add(user)
    return user.id


@pytest.fixture
async def task(store: Store, creator: uuid.UUID) -> Task:
    return await stored_task(store, creator)


async def stored_task(store: Store, creator: uuid.UUID) -> Task:
    task = a_task(creator)
    await store.tasks.add(task)
    return task


async def test_get_of_an_unknown_id_returns_none(repository: AttachmentRepository) -> None:
    assert await repository.get(uuid.uuid4()) is None


async def test_a_link_comes_back_as_it_was_stored(
    repository: AttachmentRepository, task: Task, creator: uuid.UUID
) -> None:
    link = a_link(task.id, creator, url="https://example.com/a?b=c#d", name="Swagger UI")

    await repository.add(link)

    assert await repository.get(link.id) == link


@pytest.mark.parametrize(
    ("kind", "content_type"),
    [(AttachmentKind.PDF, "application/pdf"), (AttachmentKind.IMAGE, "image/png")],
)
async def test_a_file_comes_back_as_it_was_stored(
    repository: AttachmentRepository,
    task: Task,
    creator: uuid.UUID,
    kind: AttachmentKind,
    content_type: str,
) -> None:
    file = a_file(task.id, creator, kind=kind, content_type=content_type, size_bytes=3_000_000_000)

    await repository.add(file)

    assert await repository.get(file.id) == file


async def test_the_attachments_of_a_task_are_listed_oldest_first_and_nobody_elses(
    store: Store, repository: AttachmentRepository, task: Task, creator: uuid.UUID
) -> None:
    other_task = await stored_task(store, creator)
    second = a_link(task.id, creator, name="second", now=CREATED + timedelta(minutes=2))
    first = a_file(task.id, creator, name="first.pdf", created_at=CREATED + timedelta(minutes=1))
    elsewhere = a_link(other_task.id, creator, name="elsewhere")
    for attachment in (second, first, elsewhere):
        await repository.add(attachment)

    assert list(await repository.list_for_task(task.id)) == [first, second]
    assert list(await repository.list_for_task(other_task.id)) == [elsewhere]
    assert list(await repository.list_for_task(uuid.uuid4())) == []


async def test_counts_name_every_task_asked_about_also_the_ones_with_nothing(
    store: Store, repository: AttachmentRepository, task: Task, creator: uuid.UUID
) -> None:
    bare_task = await stored_task(store, creator)
    unasked_task = await stored_task(store, creator)
    await repository.add(a_link(task.id, creator))
    await repository.add(a_file(task.id, creator))
    await repository.add(a_link(unasked_task.id, creator))

    assert await repository.count_by_task([task.id, bare_task.id]) == {task.id: 2, bare_task.id: 0}
    assert await repository.count_by_task([]) == {}


async def test_an_attachment_of_a_task_that_is_not_stored_is_refused_and_the_store_stays_usable(
    repository: AttachmentRepository, task: Task, creator: uuid.UUID
) -> None:
    orphan = a_link(uuid.uuid4(), creator)

    with pytest.raises(TaskNotFound):
        await repository.add(orphan)

    assert await repository.get(orphan.id) is None
    kept = a_link(task.id, creator)
    await repository.add(kept)
    assert await repository.get(kept.id) == kept


async def test_delete_removes_that_attachment_only(
    repository: AttachmentRepository, task: Task, creator: uuid.UUID
) -> None:
    gone, kept = a_link(task.id, creator), a_file(task.id, creator)
    await repository.add(gone)
    await repository.add(kept)

    await repository.delete(gone.id)

    assert await repository.get(gone.id) is None
    assert list(await repository.list_for_task(task.id)) == [kept]


async def test_delete_of_an_unknown_id_raises(repository: AttachmentRepository) -> None:
    unknown = uuid.uuid4()

    with pytest.raises(AttachmentNotFound) as raised:
        await repository.delete(unknown)

    assert raised.value.attachment_id == unknown


async def test_deleting_a_task_takes_its_attachments_with_it(
    store: Store, repository: AttachmentRepository, task: Task, creator: uuid.UUID
) -> None:
    other_task = await stored_task(store, creator)
    link, file, kept = (
        a_link(task.id, creator),
        a_file(task.id, creator),
        a_link(other_task.id, creator),
    )
    for attachment in (link, file, kept):
        await repository.add(attachment)

    await store.tasks.delete(task.id)

    assert await repository.get(link.id) is None
    assert await repository.get(file.id) is None
    assert list(await repository.list_for_task(task.id)) == []
    assert await repository.count_by_task([task.id, other_task.id]) == {
        task.id: 0,
        other_task.id: 1,
    }
