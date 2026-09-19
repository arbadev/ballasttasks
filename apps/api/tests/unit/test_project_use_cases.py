import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.application.errors import ProjectKeyTakenError, ProjectNotFound
from app.application.use_cases.create_project import CreateProject
from app.application.use_cases.get_project import GetProject
from app.application.use_cases.list_projects import ListProjects
from app.application.use_cases.update_project import ProjectChanges, UpdateProject
from app.domain.project import DEFAULT_PROJECT_ID, InvalidProjectError
from app.domain.task import TaskStatus
from tests.auth_fakes import InMemoryUserRepository, a_user
from tests.builders import a_project, a_task
from tests.fakes import InMemoryProjectRepository, InMemoryTaskRepository

NOW = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
LATER = NOW + timedelta(days=1)


@pytest.fixture
def projects() -> InMemoryProjectRepository:
    return InMemoryProjectRepository()


async def test_create_project_stores_it_with_no_open_tasks(
    projects: InMemoryProjectRepository,
) -> None:
    project_id = uuid.uuid4()
    create = CreateProject(projects, clock=lambda: NOW, new_id=lambda: project_id)

    overview = await create.execute(name="Ballast Tasks", key="BT", color="acc")

    assert overview.open_tasks == 0
    assert (overview.project.id, overview.project.name) == (project_id, "Ballast Tasks")
    assert (overview.project.key, overview.project.color) == ("BT", "acc")
    assert overview.project.created_at == overview.project.updated_at == NOW
    assert await projects.get(project_id) == overview.project


async def test_create_project_refuses_a_key_that_is_taken(
    projects: InMemoryProjectRepository,
) -> None:
    await CreateProject(projects).execute(name="Ballast Tasks", key="BT")

    with pytest.raises(ProjectKeyTakenError) as error:
        await CreateProject(projects).execute(name="Better Tasks", key="BT")

    assert error.value.key == "BT"
    assert [o.project.name for o in await projects.overviews()] == ["Ballast Tasks", "Inbox"]


async def test_create_project_stores_nothing_when_the_project_is_invalid(
    projects: InMemoryProjectRepository,
) -> None:
    with pytest.raises(InvalidProjectError):
        await CreateProject(projects).execute(name="Ballast Tasks", key="toolong")

    assert [o.project.key for o in await projects.overviews()] == ["IN"]


async def test_projects_are_listed_by_name_with_their_open_task_counts(
    projects: InMemoryProjectRepository,
) -> None:
    users = InMemoryUserRepository()
    tasks = InMemoryTaskRepository(users, projects)
    creator = a_user()
    await users.add(creator)
    ballast = a_project(name="ballast tasks", key="BT")
    await projects.add(ballast)
    await tasks.add(a_task(creator.id, project_id=ballast.id))
    await tasks.add(a_task(creator.id, project_id=ballast.id, status=TaskStatus.TESTING))
    await tasks.add(a_task(creator.id, project_id=ballast.id, status=TaskStatus.DONE))

    overviews = await ListProjects(projects).execute()

    assert [(o.project.key, o.open_tasks) for o in overviews] == [("BT", 2), ("IN", 0)]
    assert (await GetProject(projects).execute(ballast.id)).open_tasks == 2


async def test_get_project_of_an_unknown_id_raises_project_not_found(
    projects: InMemoryProjectRepository,
) -> None:
    project_id = uuid.uuid4()

    with pytest.raises(ProjectNotFound) as error:
        await GetProject(projects).execute(project_id)

    assert error.value.project_id == project_id


async def test_update_project_changes_only_the_given_fields(
    projects: InMemoryProjectRepository,
) -> None:
    project = a_project(color="acc")
    await projects.add(project)
    update = UpdateProject(projects, clock=lambda: LATER)

    renamed = await update.execute(project.id, ProjectChanges(name="Ballast"))
    cleared = await update.execute(project.id, ProjectChanges(color=None))

    assert (renamed.project.name, renamed.project.color) == ("Ballast", "acc")
    assert (cleared.project.name, cleared.project.color) == ("Ballast", None)
    assert cleared.project.key == "BT"
    assert cleared.project.updated_at == LATER
    assert await projects.get(project.id) == cleared.project


async def test_update_project_with_no_changes_touches_nothing(
    projects: InMemoryProjectRepository,
) -> None:
    unchanged = await UpdateProject(projects, clock=lambda: LATER).execute(
        DEFAULT_PROJECT_ID, ProjectChanges()
    )

    assert unchanged.project.updated_at < LATER


async def test_update_project_rejects_an_invalid_name_and_stores_nothing(
    projects: InMemoryProjectRepository,
) -> None:
    project = a_project()
    await projects.add(project)

    with pytest.raises(InvalidProjectError):
        await UpdateProject(projects, clock=lambda: LATER).execute(
            project.id, ProjectChanges(color="fg-3", name="   ")
        )

    assert await projects.get(project.id) == project


async def test_update_project_of_an_unknown_id_raises_project_not_found(
    projects: InMemoryProjectRepository,
) -> None:
    with pytest.raises(ProjectNotFound):
        await UpdateProject(projects).execute(uuid.uuid4(), ProjectChanges(name="x"))
