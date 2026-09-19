"""Contract every TaskRepository adapter must honour.

The in-memory fake the unit and API tests rely on runs here next to the real adapters,
so a use case tested against the fake behaves the same against PostgreSQL.
Registering a new adapter = one new entry in ``ADAPTERS`` and one branch in ``store``.

Tasks point at users (``created_by``, ``assignee_id``) and at a project, so every adapter is
paired with the user and project repositories that write to the store it references.

Filters and sorts are asserted against literal expectations over one small workspace, never
against the other adapter, and the urgency order against the design's own function
(``tests/urgency_cases.py``).
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.errors import InvalidAssigneeError, TaskNotFound, UnknownProjectError
from app.application.ports.project_repository import ProjectRepository
from app.application.ports.task_repository import TaskRepository
from app.application.ports.user_repository import UserRepository
from app.application.task_query import (
    DueFilter,
    SignalCounts,
    TaskCounts,
    TaskFilter,
    TaskQuery,
    TaskScope,
    TaskSignal,
    TaskSort,
)
from app.domain.task import Task, TaskPriority, TaskStatus
from app.domain.task_key import TaskKey
from app.infrastructure.db.engine import create_engine
from app.infrastructure.db.repositories.project import SqlAlchemyProjectRepository
from app.infrastructure.db.repositories.task import SqlAlchemyTaskRepository
from app.infrastructure.db.repositories.user import SqlAlchemyUserRepository
from tests import builders
from tests.auth_fakes import InMemoryUserRepository, a_user
from tests.builders import a_project
from tests.fakes import InMemoryProjectRepository, InMemoryTaskRepository
from tests.urgency_cases import CASES
from tests.urgency_cases import TODAY as CASES_TODAY

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
    projects: ProjectRepository


@pytest.fixture(params=ADAPTERS)
async def store(request: pytest.FixtureRequest) -> AsyncIterator[Store]:
    if request.param == "in-memory":
        users, projects = InMemoryUserRepository(), InMemoryProjectRepository()
        yield Store(InMemoryTaskRepository(users, projects), users, projects)
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
                SqlAlchemyTaskRepository(session),
                SqlAlchemyUserRepository(session),
                SqlAlchemyProjectRepository(session),
            )
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
    created_by: uuid.UUID,
    *,
    title: str = "Write the report",
    created_at: datetime = CREATED,
    **details: object,
) -> Task:
    return builders.a_task(created_by, title=title, now=created_at, **details)


EVERYTHING = TaskFilter(statuses=None)


async def every_task(repository: TaskRepository) -> list[Task]:
    """All of them, done ones included, newest first."""
    page = await repository.search(
        TaskQuery(filter=EVERYTHING, sort=TaskSort.UPDATED, limit=200), today=date(2026, 1, 5)
    )
    return list(page.items)


async def test_get_of_an_unknown_id_returns_none(repository: TaskRepository) -> None:
    assert await repository.get(uuid.uuid4()) is None


async def test_an_added_task_is_returned_with_every_field_intact(
    store: Store, repository: TaskRepository, creator: uuid.UUID
) -> None:
    project = a_project()
    await store.projects.add(project)
    task = a_task(
        creator,
        description="Q1 numbers",
        due_date=date(2026, 2, 1),
        assignee_id=await stored_user(store),
        project_id=project.id,
        key="BT-04",
        priority=TaskPriority.P0,
        importance=95,
        status=TaskStatus.TESTING,
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
    assert await every_task(repository) == []


async def test_list_returns_every_task_newest_first(
    repository: TaskRepository, creator: uuid.UUID
) -> None:
    oldest = a_task(creator, title="oldest", created_at=CREATED)
    middle = a_task(creator, title="middle", created_at=CREATED + timedelta(minutes=1))
    newest = a_task(creator, title="newest", created_at=CREATED + timedelta(minutes=2))
    for task in (middle, newest, oldest):
        await repository.add(task)

    assert await every_task(repository) == [newest, middle, oldest]


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
    task.prioritise(TaskPriority.P1, now=later)
    task.weigh(80, now=later)
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
    assert await every_task(repository) == [kept]


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
    task = a_task(creator, title="t", assignee_id=nobody)

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
    task = a_task(creator, title="t", assignee_id=left_the_team)

    await repository.add(task)

    assert await repository.get(task.id) == task


# --- tasks belong to a project and carry a key ----------------------------------------------------


async def test_a_task_is_found_by_its_key(repository: TaskRepository, creator: uuid.UUID) -> None:
    fourth, twelfth = a_task(creator, key="ZY-04"), a_task(creator, key="ZY-12")
    await repository.add(fourth)
    await repository.add(twelfth)

    assert await repository.get_by_key(TaskKey("ZY", 4)) == fourth
    assert await repository.get_by_key(TaskKey("ZY", 12)) == twelfth
    assert await repository.get_by_key(TaskKey("ZY", 5)) is None


async def test_a_task_that_moves_to_another_project_keeps_its_key(
    store: Store, repository: TaskRepository, creator: uuid.UUID
) -> None:
    project = a_project()
    await store.projects.add(project)
    task = a_task(creator, key="ZY-04")
    await repository.add(task)

    task.move_to_project(project.id, now=CREATED + timedelta(days=1))
    await repository.update(task)

    assert await repository.get_by_key(TaskKey("ZY", 4)) == task
    assert task.project_id == project.id


async def test_add_refuses_a_project_that_is_not_stored_and_stays_usable(
    repository: TaskRepository, creator: uuid.UUID
) -> None:
    nowhere = uuid.uuid4()
    task = a_task(creator, project_id=nowhere)

    with pytest.raises(UnknownProjectError) as error:
        await repository.add(task)

    assert error.value.project_id == nowhere
    assert await repository.get(task.id) is None
    kept = a_task(creator)
    await repository.add(kept)
    assert await repository.get(kept.id) == kept


async def test_update_refuses_a_project_that_is_not_stored_and_keeps_the_stored_task(
    repository: TaskRepository, creator: uuid.UUID
) -> None:
    task = a_task(creator)
    await repository.add(task)
    nowhere = uuid.uuid4()

    changed = await repository.get_for_update(task.id)
    assert changed is not None
    changed.move_to_project(nowhere, now=CREATED + timedelta(days=1))
    with pytest.raises(UnknownProjectError) as error:
        await repository.update(changed)

    assert error.value.project_id == nowhere
    assert await repository.get(task.id) == task


# --- search: the design's filters, sorts and pages ------------------------------------------------
# One workspace, looked at on TODAY. Titles are what the expectations below name.

TODAY = date(2026, 3, 10)


def due_in(days: int) -> date:
    return TODAY + timedelta(days=days)


@dataclass(frozen=True, slots=True)
class Workspace:
    me: uuid.UUID
    lucia: uuid.UUID
    ballast: uuid.UUID
    tasks: dict[str, Task]


@pytest.fixture
async def workspace(store: Store) -> Workspace:
    me, lucia = await stored_user(store), await stored_user(store)
    ballast = a_project()
    await store.projects.add(ballast)
    bt = ballast.id
    done = TaskStatus.DONE
    p0, p1, p3 = TaskPriority.P0, TaskPriority.P1, TaskPriority.P3
    rows: list[dict[str, object]] = [
        {
            "title": "overdue-mine",
            "project_id": bt,
            "status": TaskStatus.IN_PROGRESS,
            "due_date": due_in(-3),
            "priority": p1,
            "importance": 80,
            "assignee_id": me,
            "description": "FastAPI routes",
        },
        {
            "title": "p0-tomorrow",
            "project_id": bt,
            "due_date": due_in(1),
            "priority": p0,
            "importance": 95,
            "description": "Board view",
        },
        {
            "title": "today-lucia",
            "status": TaskStatus.TESTING,
            "due_date": due_in(0),
            "assignee_id": lucia,
        },
        {
            "title": "soon-p1",
            "due_date": due_in(3),
            "priority": p1,
            "importance": 40,
            "assignee_id": me,
            "description": "needs the API",
        },
        {
            "title": "next-week",
            "project_id": bt,
            "due_date": due_in(6),
            "importance": 60,
            "assignee_id": lucia,
            "description": "weekly report",
        },
        {
            "title": "far",
            "due_date": due_in(30),
            "priority": p3,
            "importance": 10,
            "assignee_id": me,
        },
        {"title": "no-date", "description": "Undated 100% _literal_"},
        {
            "title": "done-late",
            "project_id": bt,
            "status": done,
            "due_date": due_in(-5),
            "priority": p0,
            "importance": 90,
            "assignee_id": me,
            "description": "shipped API",
        },
        {"title": "done-today", "status": done, "due_date": due_in(0), "assignee_id": lucia},
    ]
    tasks: dict[str, Task] = {}
    for minutes, row in enumerate(rows):
        task = a_task(me, created_at=CREATED + timedelta(minutes=minutes), **row)  # type: ignore[arg-type]
        await store.tasks.add(task)
        tasks[task.title] = task
    return Workspace(me, lucia, bt, tasks)


OPEN = ["overdue-mine", "p0-tomorrow", "today-lucia", "soon-p1", "next-week", "far", "no-date"]


async def titles(repository: TaskRepository, query: TaskQuery) -> list[str]:
    return [task.title for task in (await repository.search(query, today=TODAY)).items]


async def test_the_default_query_is_the_open_tasks_most_urgent_first(
    repository: TaskRepository, workspace: Workspace
) -> None:
    page = await repository.search(TaskQuery(), today=TODAY)

    assert [task.title for task in page.items] == OPEN
    assert page.total == 7
    assert list(page.items) == [workspace.tasks[title] for title in OPEN]


FILTERS = {
    "everything": (lambda w: TaskFilter(statuses=None), [*OPEN, "done-late", "done-today"]),
    "one-status": (
        lambda w: TaskFilter(statuses=frozenset({TaskStatus.DONE})),
        ["done-late", "done-today"],
    ),
    "several-statuses": (
        lambda w: TaskFilter(statuses=frozenset({TaskStatus.TODO, TaskStatus.TESTING})),
        ["p0-tomorrow", "today-lucia", "soon-p1", "next-week", "far", "no-date"],
    ),
    "project": (
        lambda w: TaskFilter(project_id=w.ballast),
        ["overdue-mine", "p0-tomorrow", "next-week"],
    ),
    "unknown-project": (lambda w: TaskFilter(project_id=uuid.uuid4()), []),
    "mine": (
        lambda w: TaskFilter(scope=TaskScope.MINE, viewer_id=w.me),
        ["overdue-mine", "soon-p1", "far"],
    ),
    "mine-everything": (
        lambda w: TaskFilter(scope=TaskScope.MINE, viewer_id=w.me, statuses=None),
        ["overdue-mine", "soon-p1", "far", "done-late"],
    ),
    # A done task is never overdue, whatever the status filter says (design line 546).
    "scope-overdue": (
        lambda w: TaskFilter(scope=TaskScope.OVERDUE, statuses=None),
        ["overdue-mine"],
    ),
    "due-overdue": (lambda w: TaskFilter(due=DueFilter.OVERDUE, statuses=None), ["overdue-mine"]),
    # "today" and "week" look at the date alone, so done tasks show (design lines 551, 552).
    "due-today": (
        lambda w: TaskFilter(due=DueFilter.TODAY, statuses=None),
        ["today-lucia", "done-today"],
    ),
    "due-week": (
        lambda w: TaskFilter(due=DueFilter.WEEK, statuses=None),
        ["p0-tomorrow", "today-lucia", "soon-p1", "next-week", "done-today"],
    ),
    "due-week-open": (
        lambda w: TaskFilter(due=DueFilter.WEEK),
        ["p0-tomorrow", "today-lucia", "soon-p1", "next-week"],
    ),
    "due-none": (lambda w: TaskFilter(due=DueFilter.NONE), ["no-date"]),
    "due-before-is-inclusive": (
        lambda w: TaskFilter(due_before=due_in(1), statuses=None),
        ["overdue-mine", "p0-tomorrow", "today-lucia", "done-late", "done-today"],
    ),
    "due-after-is-inclusive": (lambda w: TaskFilter(due_after=due_in(6)), ["next-week", "far"]),
    "due-range": (
        lambda w: TaskFilter(due_after=due_in(0), due_before=due_in(3)),
        ["p0-tomorrow", "today-lucia", "soon-p1"],
    ),
    "one-priority": (
        lambda w: TaskFilter(priorities=frozenset({TaskPriority.P0})),
        ["p0-tomorrow"],
    ),
    "several-priorities": (
        lambda w: TaskFilter(
            priorities=frozenset({TaskPriority.P0, TaskPriority.P1}), statuses=None
        ),
        ["overdue-mine", "p0-tomorrow", "soon-p1", "done-late"],
    ),
    "assignee": (lambda w: TaskFilter(assignee_id=w.lucia), ["today-lucia", "next-week"]),
    "unassigned": (lambda w: TaskFilter(unassigned=True), ["p0-tomorrow", "no-date"]),
    "search-description-any-case": (
        lambda w: TaskFilter(search="api"),
        ["overdue-mine", "soon-p1"],
    ),
    "search-title-any-case": (lambda w: TaskFilter(search="SOON"), ["soon-p1"]),
    "search-everything": (
        lambda w: TaskFilter(search="Api", statuses=None),
        ["overdue-mine", "soon-p1", "done-late"],
    ),
    "search-percent-is-literal": (lambda w: TaskFilter(search="100%"), ["no-date"]),
    "search-underscore-is-literal": (lambda w: TaskFilter(search="_"), ["no-date"]),
    "search-backslash-is-literal": (lambda w: TaskFilter(search="\\"), []),
    "search-nothing": (lambda w: TaskFilter(search="zeppelin"), []),
    "signal-overdue": (lambda w: TaskFilter(signal=TaskSignal.OVERDUE), ["overdue-mine"]),
    "signal-p0-at-risk": (lambda w: TaskFilter(signal=TaskSignal.P0_AT_RISK), ["p0-tomorrow"]),
    # P0 looks 4 days ahead, P1 3, the rest 2: "soon-p1" is in, "next-week" is not.
    "signal-due-soon": (
        lambda w: TaskFilter(signal=TaskSignal.DUE_SOON),
        ["p0-tomorrow", "today-lucia", "soon-p1"],
    ),
    "signal-needs-owner": (
        lambda w: TaskFilter(signal=TaskSignal.NEEDS_OWNER),
        ["p0-tomorrow", "no-date"],
    ),
    "combined": (
        lambda w: TaskFilter(
            project_id=w.ballast, scope=TaskScope.MINE, viewer_id=w.me, statuses=None, search="a"
        ),
        ["overdue-mine", "done-late"],
    ),
}


@pytest.mark.parametrize("name", FILTERS)
async def test_search_filters(repository: TaskRepository, workspace: Workspace, name: str) -> None:
    build, expected = FILTERS[name]
    query = TaskQuery(filter=build(workspace))

    page = await repository.search(query, today=TODAY)

    assert [task.title for task in page.items] == expected
    assert page.total == len(expected)


SORTS = {
    TaskSort.URGENCY: [*OPEN, "done-late", "done-today"],
    # Equal importance: the newer task first.
    TaskSort.IMPORTANCE: [
        "p0-tomorrow",
        "done-late",
        "overdue-mine",
        "next-week",
        "done-today",
        "no-date",
        "today-lucia",
        "soon-p1",
        "far",
    ],
    # Earliest first, undated last; the same day: the more important, then the newer, first.
    TaskSort.DUE_DATE: [
        "done-late",
        "overdue-mine",
        "done-today",
        "today-lucia",
        "p0-tomorrow",
        "soon-p1",
        "next-week",
        "far",
        "no-date",
    ],
    TaskSort.UPDATED: [
        "done-today",
        "done-late",
        "no-date",
        "far",
        "next-week",
        "soon-p1",
        "today-lucia",
        "p0-tomorrow",
        "overdue-mine",
    ],
}


@pytest.mark.parametrize("sort", SORTS)
async def test_search_sorts(
    repository: TaskRepository, workspace: Workspace, sort: TaskSort
) -> None:
    assert await titles(repository, TaskQuery(filter=EVERYTHING, sort=sort)) == SORTS[sort]


async def test_recently_updated_follows_updated_at(
    repository: TaskRepository, workspace: Workspace
) -> None:
    touched = workspace.tasks["soon-p1"]
    touched.retitle("soon-p1 (edited)", now=CREATED + timedelta(days=1))
    await repository.update(touched)

    ordered = await titles(repository, TaskQuery(sort=TaskSort.UPDATED, limit=2))

    assert ordered == ["soon-p1 (edited)", "no-date"]


async def test_the_same_tasks_on_another_day_are_ordered_by_that_day(
    repository: TaskRepository, workspace: Workspace
) -> None:
    a_month_later = await repository.search(
        TaskQuery(filter=TaskFilter(scope=TaskScope.OVERDUE)), today=due_in(31)
    )

    # Everything dated is overdue by then; "far" by one day, the others by more.
    assert [task.title for task in a_month_later.items] == [
        "p0-tomorrow",
        "overdue-mine",
        "next-week",
        "soon-p1",
        "today-lucia",
        "far",
    ]


async def test_search_pages_with_limit_and_offset_and_always_reports_the_total(
    repository: TaskRepository, workspace: Workspace
) -> None:
    first = await repository.search(TaskQuery(limit=3), today=TODAY)
    second = await repository.search(TaskQuery(limit=3, offset=3), today=TODAY)
    last = await repository.search(TaskQuery(limit=3, offset=6), today=TODAY)
    beyond = await repository.search(TaskQuery(limit=3, offset=7), today=TODAY)

    assert [task.title for task in first.items] == OPEN[:3]
    assert [task.title for task in second.items] == OPEN[3:6]
    assert [task.title for task in last.items] == OPEN[6:]
    assert list(beyond.items) == []
    assert {page.total for page in (first, second, last, beyond)} == {7}


async def test_open_tasks_are_counted_for_the_sidebar(
    repository: TaskRepository, workspace: Workspace
) -> None:
    mine = await repository.count_open(viewer_id=workspace.me, today=TODAY)
    hers = await repository.count_open(viewer_id=workspace.lucia, today=TODAY)
    a_stranger = await repository.count_open(viewer_id=uuid.uuid4(), today=due_in(31))

    assert mine == TaskCounts(all=7, mine=3, overdue=1)
    assert hers == TaskCounts(all=7, mine=2, overdue=1)
    assert a_stranger == TaskCounts(all=7, mine=0, overdue=6)


async def test_nothing_is_counted_in_an_empty_store(repository: TaskRepository) -> None:
    assert await repository.count_open(viewer_id=uuid.uuid4(), today=TODAY) == TaskCounts(0, 0, 0)
    assert await repository.count_signals(TaskFilter(), today=TODAY) == SignalCounts(0, 0, 0, 0)


async def test_signals_are_counted_over_the_tasks_a_filter_selects(
    repository: TaskRepository, workspace: Workspace
) -> None:
    everywhere = await repository.count_signals(TaskFilter(), today=TODAY)
    in_ballast = await repository.count_signals(
        TaskFilter(project_id=workspace.ballast), today=TODAY
    )
    of_done_tasks = await repository.count_signals(
        TaskFilter(statuses=frozenset({TaskStatus.DONE})), today=TODAY
    )

    assert everywhere == SignalCounts(overdue=1, p0_at_risk=1, due_soon=3, needs_owner=2)
    assert in_ballast == SignalCounts(overdue=1, p0_at_risk=1, due_soon=1, needs_owner=1)
    assert of_done_tasks == SignalCounts(0, 0, 0, 0)


async def test_the_urgency_order_is_the_design_function_over_the_table_of_cases(
    store: Store, repository: TaskRepository, creator: uuid.UUID
) -> None:
    project = a_project(name="Urgency", key="UR")
    await store.projects.add(project)
    expected_scores: dict[uuid.UUID, float] = {}
    for number, case in enumerate(CASES, start=1):
        task = case.task(created_by=creator, project_id=project.id, number=number)
        await repository.add(task)
        expected_scores[task.id] = case.expected.score

    found: list[uuid.UUID] = []
    while len(found) < len(CASES):
        page = await repository.search(
            TaskQuery(filter=EVERYTHING, limit=200, offset=len(found)), today=CASES_TODAY
        )
        assert page.total == len(CASES)
        found.extend(task.id for task in page.items)

    # The design's score, highest first; the cases share one created_at, so ties fall back to
    # the id, descending.
    by_design = sorted(expected_scores, key=lambda i: (-expected_scores[i], -i.int))
    assert found == by_design
