"""Contract every ProjectRepository adapter must honour (Liskov).

The in-memory fake runs everywhere; the SQLAlchemy adapter runs the same cases under the
``integration`` marker against a freshly migrated PostgreSQL database, which already holds
the Inbox. Open-task counts read the tasks table, so each adapter comes with the task and
user repositories of the same store. What needs two transactions at once (the key counter
under concurrency) lives in ``tests/integration/test_task_key_allocation.py``.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta

import pytest
from app.infrastructure.db.repositories.project import SqlAlchemyProjectRepository
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.errors import ProjectKeyTakenError, ProjectNotFound, UnknownProjectError
from app.application.ports.project_repository import ProjectOverview, ProjectRepository
from app.application.ports.task_repository import TaskRepository
from app.application.ports.user_repository import UserRepository
from app.domain.project import DEFAULT_PROJECT_ID
from app.domain.task import TaskStatus
from app.domain.task_key import TaskKey
from app.infrastructure.db.engine import create_engine
from app.infrastructure.db.repositories.task import SqlAlchemyTaskRepository
from app.infrastructure.db.repositories.user import SqlAlchemyUserRepository
from tests.auth_fakes import InMemoryUserRepository, a_user
from tests.builders import CREATED, a_project, a_task
from tests.fakes import InMemoryProjectRepository, InMemoryTaskRepository

ADAPTERS = [
    pytest.param("in-memory"),
    pytest.param("sqlalchemy-postgresql", marks=pytest.mark.integration),
]


@dataclass(frozen=True, slots=True)
class Store:
    projects: ProjectRepository
    tasks: TaskRepository
    users: UserRepository


@pytest.fixture(params=ADAPTERS)
async def store(request: pytest.FixtureRequest) -> AsyncIterator[Store]:
    if request.param == "in-memory":
        users, projects = InMemoryUserRepository(), InMemoryProjectRepository()
        yield Store(projects, InMemoryTaskRepository(users, projects), users)
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
                SqlAlchemyProjectRepository(session),
                SqlAlchemyTaskRepository(session),
                SqlAlchemyUserRepository(session),
            )
        await transaction.rollback()
    await engine.dispose()


@pytest.fixture
def projects(store: Store) -> ProjectRepository:
    return store.projects


async def test_every_store_starts_with_the_inbox(projects: ProjectRepository) -> None:
    inbox = await projects.get(DEFAULT_PROJECT_ID)

    assert inbox is not None
    assert (inbox.name, inbox.key, inbox.color) == ("Inbox", "IN", None)
    assert inbox.created_at.utcoffset() == timedelta(0)


async def test_an_added_project_is_returned_with_every_field_intact(
    projects: ProjectRepository,
) -> None:
    coloured, plain = a_project(color="acc"), a_project(name="Plain", key="PL")

    await projects.add(coloured)
    await projects.add(plain)

    assert await projects.get(coloured.id) == coloured
    assert await projects.get(plain.id) == plain
    assert await projects.get_for_update(plain.id) == plain


async def test_an_unknown_id_is_none(projects: ProjectRepository) -> None:
    assert await projects.get(uuid.uuid4()) is None
    assert await projects.get_for_update(uuid.uuid4()) is None
    assert await projects.overview(uuid.uuid4()) is None


async def test_a_taken_key_is_refused_and_the_repository_stays_usable(
    projects: ProjectRepository,
) -> None:
    first, second = a_project(key="BT"), a_project(name="Better Tasks", key="BT")
    await projects.add(first)

    with pytest.raises(ProjectKeyTakenError) as error:
        await projects.add(second)

    assert error.value.key == "BT"
    assert await projects.get(second.id) is None
    assert await projects.get(first.id) == first
    third = a_project(name="Other", key="OT")
    await projects.add(third)
    assert await projects.get(third.id) == third


async def test_the_inbox_key_is_taken_from_the_start(projects: ProjectRepository) -> None:
    with pytest.raises(ProjectKeyTakenError):
        await projects.add(a_project(name="Incoming", key="IN"))


async def test_changes_are_stored_only_by_update(projects: ProjectRepository) -> None:
    project = a_project()
    await projects.add(project)
    later = CREATED + timedelta(days=1)

    loaded = await projects.get_for_update(project.id)
    assert loaded is not None
    loaded.rename("Ballast", now=later)
    loaded.recolor("fg-3", now=later)
    assert await projects.get(project.id) == project

    await projects.update(loaded)

    stored = await projects.get(project.id)
    assert stored == loaded
    assert stored is not None
    assert (stored.created_at, stored.updated_at) == (CREATED, later)


async def test_update_of_an_unknown_project_raises_project_not_found(
    projects: ProjectRepository,
) -> None:
    ghost = a_project()

    with pytest.raises(ProjectNotFound) as error:
        await projects.update(ghost)

    assert error.value.project_id == ghost.id


async def test_overviews_are_by_name_whatever_the_case_with_open_task_counts(
    store: Store,
) -> None:
    creator = a_user()
    await store.users.add(creator)
    zulu, ballast = a_project(name="Zulu", key="ZU"), a_project(name="ballast tasks", key="BT")
    await store.projects.add(zulu)
    await store.projects.add(ballast)
    for status in (TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.TESTING, TaskStatus.DONE):
        await store.tasks.add(a_task(creator.id, project_id=ballast.id, status=status))
    await store.tasks.add(a_task(creator.id, status=TaskStatus.DONE))

    overviews = await store.projects.overviews()

    assert list(overviews) == [
        ProjectOverview(ballast, 3),
        ProjectOverview(await store.projects.get(DEFAULT_PROJECT_ID), 0),  # type: ignore[arg-type]
        ProjectOverview(zulu, 0),
    ]
    assert await store.projects.overview(ballast.id) == ProjectOverview(ballast, 3)
    assert await store.projects.overview(zulu.id) == ProjectOverview(zulu, 0)


async def test_task_keys_count_up_from_one_in_each_project(projects: ProjectRepository) -> None:
    ballast = a_project(key="BT")
    await projects.add(ballast)

    keys = [
        await projects.allocate_task_key(ballast.id),
        await projects.allocate_task_key(DEFAULT_PROJECT_ID),
        await projects.allocate_task_key(ballast.id),
        await projects.allocate_task_key(ballast.id),
        await projects.allocate_task_key(DEFAULT_PROJECT_ID),
    ]

    assert keys == [
        TaskKey("BT", 1),
        TaskKey("IN", 1),
        TaskKey("BT", 2),
        TaskKey("BT", 3),
        TaskKey("IN", 2),
    ]


async def test_handing_out_keys_does_not_change_the_project(projects: ProjectRepository) -> None:
    ballast = a_project(key="BT")
    await projects.add(ballast)

    await projects.allocate_task_key(ballast.id)

    assert await projects.get(ballast.id) == ballast


async def test_no_key_is_handed_out_for_a_project_that_does_not_exist(
    projects: ProjectRepository,
) -> None:
    nowhere = uuid.uuid4()

    with pytest.raises(UnknownProjectError) as error:
        await projects.allocate_task_key(nowhere)

    assert error.value.project_id == nowhere
