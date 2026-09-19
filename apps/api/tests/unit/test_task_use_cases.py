import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from app.application.errors import InvalidAssigneeError, TaskNotFound
from app.application.use_cases.create_task import CreateTask
from app.application.use_cases.delete_task import DeleteTask
from app.application.use_cases.get_task import GetTask
from app.application.use_cases.list_tasks import ListTasks
from app.application.use_cases.update_task import TaskChanges, UpdateTask
from app.domain.task import InvalidTaskError, Task, TaskStatus
from tests.auth_fakes import InMemoryUserDirectory, InMemoryUserRepository, a_user
from tests.fakes import InMemoryTaskRepository

NOW = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
LATER = NOW + timedelta(days=1)
CREATOR = uuid.uuid4()


@pytest.fixture
def users() -> InMemoryUserRepository:
    return InMemoryUserRepository()


@pytest.fixture
def directory(users: InMemoryUserRepository) -> InMemoryUserDirectory:
    return InMemoryUserDirectory(users)


@pytest.fixture
def tasks(users: InMemoryUserRepository) -> InMemoryTaskRepository:
    return InMemoryTaskRepository(users)


async def stored_user(users: InMemoryUserRepository, *, is_active: bool = True) -> uuid.UUID:
    user = a_user(is_active=is_active)
    await users.add(user)
    return user.id


async def stored_task(tasks: InMemoryTaskRepository, *, title: str = "Write the report") -> Task:
    task = Task.create(task_id=uuid.uuid4(), title=title, created_by=CREATOR, now=NOW)
    await tasks.add(task)
    return task


async def test_create_task_stores_a_todo_task_owned_by_its_creator(
    tasks: InMemoryTaskRepository,
    users: InMemoryUserRepository,
    directory: InMemoryUserDirectory,
) -> None:
    task_id, assignee = uuid.uuid4(), await stored_user(users)
    create_task = CreateTask(tasks, directory, clock=lambda: NOW, new_id=lambda: task_id)

    task = await create_task.execute(
        title="Write the report",
        description="Q1 numbers",
        due_date=date(2026, 2, 1),
        assignee_id=assignee,
        created_by=CREATOR,
    )

    assert task.id == task_id
    assert task.status is TaskStatus.TODO
    assert task.created_by == CREATOR
    assert task.assignee_id == assignee
    assert task.created_at == task.updated_at == NOW
    assert await tasks.get(task_id) == task


async def test_create_task_generates_ids_and_utc_timestamps_by_default(
    tasks: InMemoryTaskRepository, directory: InMemoryUserDirectory
) -> None:
    create_task = CreateTask(tasks, directory)

    first = await create_task.execute(title="one", created_by=CREATOR)
    second = await create_task.execute(title="two", created_by=CREATOR)

    assert first.id != second.id
    assert first.created_at.utcoffset() == timedelta(0)


async def test_create_task_stores_nothing_when_the_task_is_invalid(
    tasks: InMemoryTaskRepository, directory: InMemoryUserDirectory
) -> None:
    with pytest.raises(InvalidTaskError):
        await CreateTask(tasks, directory).execute(title="   ", created_by=CREATOR)

    assert list(await tasks.list()) == []


@pytest.mark.parametrize("assignee", ["unknown", "inactive"])
async def test_create_task_rejects_an_assignee_who_is_not_an_active_user_and_stores_nothing(
    tasks: InMemoryTaskRepository,
    users: InMemoryUserRepository,
    directory: InMemoryUserDirectory,
    assignee: str,
) -> None:
    assignee_id = (
        uuid.uuid4() if assignee == "unknown" else await stored_user(users, is_active=False)
    )

    with pytest.raises(InvalidAssigneeError) as error:
        await CreateTask(tasks, directory).execute(
            title="Write the report", created_by=CREATOR, assignee_id=assignee_id
        )

    assert error.value.assignee_id == assignee_id
    assert list(await tasks.list()) == []


async def test_create_task_rejects_a_broken_domain_rule_before_it_looks_the_assignee_up(
    tasks: InMemoryTaskRepository, directory: InMemoryUserDirectory
) -> None:
    with pytest.raises(InvalidTaskError):
        await CreateTask(tasks, directory).execute(
            title="   ", created_by=CREATOR, assignee_id=uuid.uuid4()
        )


async def test_get_task_returns_the_stored_task(tasks: InMemoryTaskRepository) -> None:
    task = await stored_task(tasks)

    assert await GetTask(tasks).execute(task.id) == task


async def test_get_task_raises_task_not_found_for_an_unknown_id(
    tasks: InMemoryTaskRepository,
) -> None:
    task_id = uuid.uuid4()

    with pytest.raises(TaskNotFound, match=str(task_id)):
        await GetTask(tasks).execute(task_id)


async def test_list_tasks_returns_what_the_repository_holds(
    tasks: InMemoryTaskRepository,
) -> None:
    task = await stored_task(tasks)

    assert list(await ListTasks(tasks).execute()) == [task]


async def test_update_task_changes_only_the_given_fields(
    tasks: InMemoryTaskRepository, directory: InMemoryUserDirectory
) -> None:
    task = await stored_task(tasks)
    await UpdateTask(tasks, directory, clock=lambda: NOW).execute(
        task.id, TaskChanges(description="Q1 numbers", due_date=date(2026, 2, 1))
    )

    updated = await UpdateTask(tasks, directory, clock=lambda: LATER).execute(
        task.id, TaskChanges(title="Publish the report")
    )

    assert updated.title == "Publish the report"
    assert updated.description == "Q1 numbers"
    assert updated.due_date == date(2026, 2, 1)
    assert updated.updated_at == LATER
    assert await tasks.get(task.id) == updated


async def test_update_task_marks_a_task_completed_and_reopens_it(
    tasks: InMemoryTaskRepository, directory: InMemoryUserDirectory
) -> None:
    task = await stored_task(tasks)
    update_task = UpdateTask(tasks, directory, clock=lambda: LATER)

    done = await update_task.execute(task.id, TaskChanges(status=TaskStatus.DONE))
    assert done.status is TaskStatus.DONE
    assert done.completed_at == LATER

    reopened = await update_task.execute(task.id, TaskChanges(status=TaskStatus.IN_PROGRESS))
    assert reopened.completed_at is None
    stored = await tasks.get(task.id)
    assert stored is not None
    assert stored.status is TaskStatus.IN_PROGRESS


async def test_update_task_assigns_and_unassigns(
    tasks: InMemoryTaskRepository,
    users: InMemoryUserRepository,
    directory: InMemoryUserDirectory,
) -> None:
    task = await stored_task(tasks)
    assignee = await stored_user(users)
    update_task = UpdateTask(tasks, directory, clock=lambda: LATER)

    assigned = await update_task.execute(task.id, TaskChanges(assignee_id=assignee))
    assert assigned.assignee_id == assignee

    unassigned = await update_task.execute(task.id, TaskChanges(assignee_id=None))
    assert unassigned.assignee_id is None


async def test_update_task_can_clear_the_optional_fields(
    tasks: InMemoryTaskRepository, directory: InMemoryUserDirectory
) -> None:
    task = await stored_task(tasks)
    update_task = UpdateTask(tasks, directory, clock=lambda: LATER)
    await update_task.execute(
        task.id, TaskChanges(description="Q1 numbers", due_date=date(2026, 2, 1))
    )

    cleared = await update_task.execute(task.id, TaskChanges(description=None, due_date=None))

    assert cleared.description is None
    assert cleared.due_date is None


async def test_update_task_without_changes_leaves_the_task_untouched(
    tasks: InMemoryTaskRepository, directory: InMemoryUserDirectory
) -> None:
    task = await stored_task(tasks)

    unchanged = await UpdateTask(tasks, directory, clock=lambda: LATER).execute(
        task.id, TaskChanges()
    )

    assert unchanged == task
    assert unchanged.updated_at == NOW


async def test_update_task_stores_nothing_when_a_change_is_invalid(
    tasks: InMemoryTaskRepository, directory: InMemoryUserDirectory
) -> None:
    task = await stored_task(tasks)

    with pytest.raises(InvalidTaskError):
        await UpdateTask(tasks, directory, clock=lambda: LATER).execute(
            task.id, TaskChanges(status=TaskStatus.DONE, title="   ")
        )

    assert await tasks.get(task.id) == task


async def test_update_task_raises_task_not_found_for_an_unknown_id(
    tasks: InMemoryTaskRepository, directory: InMemoryUserDirectory
) -> None:
    with pytest.raises(TaskNotFound):
        await UpdateTask(tasks, directory).execute(uuid.uuid4(), TaskChanges(title="x"))


@pytest.mark.parametrize("assignee", ["unknown", "inactive"])
async def test_update_task_rejects_an_assignee_who_is_not_an_active_user_and_stores_nothing(
    tasks: InMemoryTaskRepository,
    users: InMemoryUserRepository,
    directory: InMemoryUserDirectory,
    assignee: str,
) -> None:
    task = await stored_task(tasks)
    assignee_id = (
        uuid.uuid4() if assignee == "unknown" else await stored_user(users, is_active=False)
    )

    with pytest.raises(InvalidAssigneeError) as error:
        await UpdateTask(tasks, directory, clock=lambda: LATER).execute(
            task.id, TaskChanges(title="Publish the report", assignee_id=assignee_id)
        )

    assert error.value.assignee_id == assignee_id
    assert await tasks.get(task.id) == task


async def test_update_task_does_not_recheck_an_assignee_the_request_leaves_alone(
    tasks: InMemoryTaskRepository,
    users: InMemoryUserRepository,
    directory: InMemoryUserDirectory,
) -> None:
    """Someone deactivated after being assigned must not freeze the task: it can still be
    completed, edited, and handed to somebody else."""
    left_the_team = await stored_user(users, is_active=False)
    task = Task.create(
        task_id=uuid.uuid4(),
        title="Write the report",
        created_by=CREATOR,
        assignee_id=left_the_team,
        now=NOW,
    )
    await tasks.add(task)

    done = await UpdateTask(tasks, directory, clock=lambda: LATER).execute(
        task.id, TaskChanges(status=TaskStatus.DONE)
    )

    assert done.status is TaskStatus.DONE
    assert done.assignee_id == left_the_team


async def test_update_task_accepts_a_change_that_names_the_deactivated_assignee_it_already_has(
    tasks: InMemoryTaskRepository,
    users: InMemoryUserRepository,
    directory: InMemoryUserDirectory,
) -> None:
    """A client that sends the whole task back names the assignee without changing it."""
    left_the_team = await stored_user(users, is_active=False)
    task = Task.create(
        task_id=uuid.uuid4(),
        title="Write the report",
        created_by=CREATOR,
        assignee_id=left_the_team,
        now=NOW,
    )
    await tasks.add(task)

    updated = await UpdateTask(tasks, directory, clock=lambda: LATER).execute(
        task.id, TaskChanges(title="Publish the report", assignee_id=left_the_team)
    )

    assert updated.title == "Publish the report"
    assert updated.assignee_id == left_the_team
    assert await tasks.get(task.id) == updated


@pytest.mark.parametrize("assignee", ["unknown", "inactive"])
async def test_update_task_rejects_a_change_from_a_deactivated_assignee_to_somebody_not_active(
    tasks: InMemoryTaskRepository,
    users: InMemoryUserRepository,
    directory: InMemoryUserDirectory,
    assignee: str,
) -> None:
    left_the_team = await stored_user(users, is_active=False)
    task = Task.create(
        task_id=uuid.uuid4(),
        title="Write the report",
        created_by=CREATOR,
        assignee_id=left_the_team,
        now=NOW,
    )
    await tasks.add(task)
    assignee_id = (
        uuid.uuid4() if assignee == "unknown" else await stored_user(users, is_active=False)
    )

    with pytest.raises(InvalidAssigneeError) as error:
        await UpdateTask(tasks, directory, clock=lambda: LATER).execute(
            task.id, TaskChanges(title="Publish the report", assignee_id=assignee_id)
        )

    assert error.value.assignee_id == assignee_id
    assert await tasks.get(task.id) == task


async def test_update_task_reports_an_unknown_task_before_an_unknown_assignee(
    tasks: InMemoryTaskRepository, directory: InMemoryUserDirectory
) -> None:
    with pytest.raises(TaskNotFound):
        await UpdateTask(tasks, directory).execute(
            uuid.uuid4(), TaskChanges(assignee_id=uuid.uuid4())
        )


async def test_delete_task_removes_the_task(tasks: InMemoryTaskRepository) -> None:
    task = await stored_task(tasks)

    await DeleteTask(tasks).execute(task.id)

    assert await tasks.get(task.id) is None


async def test_delete_task_raises_task_not_found_for_an_unknown_id(
    tasks: InMemoryTaskRepository,
) -> None:
    with pytest.raises(TaskNotFound):
        await DeleteTask(tasks).execute(uuid.uuid4())
