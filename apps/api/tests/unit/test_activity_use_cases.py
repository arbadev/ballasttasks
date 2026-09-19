"""Comments, the activity feed, and what creating and changing a task leaves in the log."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pytest

from app.application.errors import InvalidAssigneeError, TaskNotFound
from app.application.ports.activity_feed import ActivityItem
from app.application.use_cases.create_task import CreateTask
from app.application.use_cases.list_activity import ListActivity
from app.application.use_cases.post_comment import PostComment
from app.application.use_cases.update_task import TaskChanges, UpdateTask
from app.domain.activity import ActivityEntry, ActivityKind, Actor, InvalidActivityError
from app.domain.task import InvalidTaskError, Task, TaskPriority, TaskStatus
from app.domain.user import User
from tests.activity_fakes import InMemoryActivityLog
from tests.auth_fakes import InMemoryUserDirectory, InMemoryUserRepository, a_user
from tests.builders import a_task
from tests.fakes import InMemoryProjectRepository, InMemoryTaskRepository

NOW = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=2)
TODAY = LATER.date()


@dataclass(frozen=True, slots=True)
class World:
    users: InMemoryUserRepository
    tasks: InMemoryTaskRepository
    activity: InMemoryActivityLog
    andres: User
    lucia: User

    @property
    def directory(self) -> InMemoryUserDirectory:
        return InMemoryUserDirectory(self.users)

    @property
    def create_task(self) -> CreateTask:
        return CreateTask(
            self.tasks, self.directory, self.tasks.projects, self.activity, clock=lambda: NOW
        )

    @property
    def update_task(self) -> UpdateTask:
        return UpdateTask(
            self.tasks, self.directory, self.tasks.projects, self.activity, clock=lambda: LATER
        )

    @property
    def post_comment(self) -> PostComment:
        return PostComment(self.tasks, self.activity, self.directory, clock=lambda: LATER)

    async def a_stored_task(self, **overrides: object) -> Task:
        task = a_task(self.andres.id, now=NOW, **overrides)
        await self.tasks.add(task)
        return task


@pytest.fixture
async def world() -> World:
    users = InMemoryUserRepository()
    tasks = InMemoryTaskRepository(users, InMemoryProjectRepository())
    andres, lucia = a_user(full_name="Andres Barradas"), a_user(full_name="Lucía Marín")
    await users.add(andres)
    await users.add(lucia)
    return World(users, tasks, InMemoryActivityLog(tasks), andres, lucia)


# --- create -------------------------------------------------------------------------------


async def test_creating_a_task_is_its_first_entry(world: World) -> None:
    task = await world.create_task.execute(title="Write the report", created_by=world.andres.id)

    (entry,) = world.activity.entries
    assert (entry.task_id, entry.kind, entry.text) == (
        task.id,
        ActivityKind.LOG,
        "Created the task",
    )
    assert (entry.actor_id, entry.created_at) == (world.andres.id, NOW)


async def test_a_task_created_straight_into_a_column_or_for_somebody_is_still_one_entry(
    world: World,
) -> None:
    task = await world.create_task.execute(
        title="Write the report",
        created_by=world.andres.id,
        status=TaskStatus.DONE,
        assignee_id=world.lucia.id,
        due_date=TODAY,
        priority=TaskPriority.P0,
    )

    assert world.activity.texts(task.id) == ["Created the task"]


async def test_a_task_that_is_refused_leaves_no_entry(world: World) -> None:
    with pytest.raises(InvalidTaskError):
        await world.create_task.execute(title="   ", created_by=world.andres.id)
    with pytest.raises(InvalidAssigneeError):
        await world.create_task.execute(
            title="Write the report", created_by=world.andres.id, assignee_id=uuid.uuid4()
        )

    assert world.activity.entries == []


# --- update(id, patch, logText) -------------------------------------------------------------


@pytest.mark.parametrize(
    ("changes", "text"),
    [
        (TaskChanges(status=TaskStatus.IN_PROGRESS), "Moved To Do → In Progress"),
        (TaskChanges(status=TaskStatus.DONE), "Moved To Do → Done"),
        (TaskChanges(due_date=TODAY + timedelta(days=1)), "Due date moved to tomorrow"),
        (TaskChanges(due_date=TODAY + timedelta(days=7)), "Due date moved a week out"),
        (TaskChanges(due_date=date(2026, 3, 9)), "Due date moved to Mar 9"),
        (TaskChanges(priority=TaskPriority.P0), "Priority P2 → P0"),
    ],
)
async def test_a_logged_change_leaves_its_line_by_whoever_made_it(
    world: World, changes: TaskChanges, text: str
) -> None:
    task = await world.a_stored_task()

    await world.update_task.execute(task.id, changes, actor_id=world.lucia.id)

    (entry,) = world.activity.entries
    assert (entry.task_id, entry.kind, entry.text) == (task.id, ActivityKind.LOG, text)
    assert (entry.actor_id, entry.created_at) == (world.lucia.id, LATER)


async def test_assigning_names_the_assignee_and_clearing_says_unassigned(world: World) -> None:
    task = await world.a_stored_task()

    await world.update_task.execute(
        task.id, TaskChanges(assignee_id=world.lucia.id), actor_id=world.andres.id
    )
    await world.update_task.execute(
        task.id, TaskChanges(assignee_id=None), actor_id=world.andres.id
    )

    assert world.activity.texts(task.id) == ["Assigned to Lucía Marín", "Unassigned"]


async def test_reopening_is_a_move_out_of_done(world: World) -> None:
    task = await world.a_stored_task(status=TaskStatus.DONE)

    await world.update_task.execute(
        task.id, TaskChanges(status=TaskStatus.TODO), actor_id=world.andres.id
    )

    assert world.activity.texts(task.id) == ["Moved Done → To Do"]


async def test_clearing_the_due_date_is_logged(world: World) -> None:
    task = await world.a_stored_task(due_date=TODAY)

    await world.update_task.execute(task.id, TaskChanges(due_date=None), actor_id=world.andres.id)

    assert world.activity.texts(task.id) == ["Due date cleared"]


async def test_one_change_of_several_fields_leaves_a_line_for_each(world: World) -> None:
    task = await world.a_stored_task()

    await world.update_task.execute(
        task.id,
        TaskChanges(
            title="Publish the report",
            priority=TaskPriority.P1,
            status=TaskStatus.TESTING,
            assignee_id=world.lucia.id,
        ),
        actor_id=world.andres.id,
    )

    assert world.activity.texts(task.id) == [
        "Moved To Do → Testing",
        "Assigned to Lucía Marín",
        "Priority P2 → P1",
    ]


async def test_a_change_that_alters_nothing_records_nothing(world: World) -> None:
    task = await world.a_stored_task(
        status=TaskStatus.TESTING, assignee_id=world.lucia.id, due_date=TODAY
    )

    for same in (
        TaskChanges(),
        TaskChanges(status=TaskStatus.TESTING),
        TaskChanges(assignee_id=world.lucia.id),
        TaskChanges(due_date=TODAY, priority=TaskPriority.P2),
    ):
        await world.update_task.execute(task.id, same, actor_id=world.andres.id)

    assert world.activity.entries == []


async def test_fields_the_design_edits_silently_record_nothing(world: World) -> None:
    task = await world.a_stored_task()

    await world.update_task.execute(
        task.id,
        TaskChanges(title="Another", description="More", importance=90),
        actor_id=world.andres.id,
    )

    assert world.activity.entries == []


async def test_a_change_that_is_refused_records_nothing(world: World) -> None:
    task = await world.a_stored_task()

    with pytest.raises(InvalidAssigneeError):
        await world.update_task.execute(
            task.id,
            TaskChanges(status=TaskStatus.DONE, assignee_id=uuid.uuid4()),
            actor_id=world.andres.id,
        )
    with pytest.raises(TaskNotFound):
        await world.update_task.execute(
            uuid.uuid4(), TaskChanges(status=TaskStatus.DONE), actor_id=world.andres.id
        )

    assert world.activity.entries == []


# --- comments -----------------------------------------------------------------------------


async def test_a_comment_is_an_entry_by_the_caller_and_touches_the_task(world: World) -> None:
    task = await world.a_stored_task()
    entry_id = uuid.uuid4()
    post_comment = PostComment(
        world.tasks, world.activity, world.directory, clock=lambda: LATER, new_id=lambda: entry_id
    )

    item = await post_comment.execute(task.id, text="  Looks good ", actor_id=world.lucia.id)

    entry = ActivityEntry(
        id=entry_id,
        task_id=task.id,
        kind=ActivityKind.COMMENT,
        text="Looks good",
        actor_id=world.lucia.id,
        created_at=LATER,
    )
    assert item == ActivityItem(entry, Actor(id=world.lucia.id, full_name="Lucía Marín"))
    assert world.activity.entries == [entry]
    stored = await world.tasks.get(task.id)
    assert stored is not None
    assert stored.updated_at == LATER


@pytest.mark.parametrize("text", ["", "   ", "x" * 2001, "nul\x00byte"])
async def test_a_comment_that_cannot_be_stored_is_refused(world: World, text: str) -> None:
    task = await world.a_stored_task()

    with pytest.raises(InvalidActivityError):
        await world.post_comment.execute(task.id, text=text, actor_id=world.andres.id)

    assert world.activity.entries == []
    stored = await world.tasks.get(task.id)
    assert stored is not None
    assert stored.updated_at == NOW


async def test_nobody_comments_on_a_task_that_does_not_exist(world: World) -> None:
    with pytest.raises(TaskNotFound):
        await world.post_comment.execute(uuid.uuid4(), text="hello?", actor_id=world.andres.id)

    assert world.activity.entries == []


# --- the feed -----------------------------------------------------------------------------


async def test_the_feed_is_newest_first_and_paged(world: World) -> None:
    task = await world.create_task.execute(title="Write the report", created_by=world.andres.id)
    await world.update_task.execute(
        task.id, TaskChanges(status=TaskStatus.DONE), actor_id=world.lucia.id
    )
    await world.post_comment.execute(task.id, text="Shipped", actor_id=world.lucia.id)
    list_activity = ListActivity(world.tasks, world.activity)

    everything = await list_activity.execute(task.id, limit=50, offset=0)
    second_page = await list_activity.execute(task.id, limit=2, offset=2)

    assert [(i.entry.text, i.actor.full_name) for i in everything.items] == [
        ("Shipped", "Lucía Marín"),
        ("Moved To Do → Done", "Lucía Marín"),
        ("Created the task", "Andres Barradas"),
    ]
    assert everything.total == 3
    assert [i.entry.text for i in second_page.items] == ["Created the task"]
    assert second_page.total == 3


async def test_a_task_that_does_not_exist_has_no_feed(world: World) -> None:
    with pytest.raises(TaskNotFound):
        await ListActivity(world.tasks, world.activity).execute(uuid.uuid4(), limit=50, offset=0)
