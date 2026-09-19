"""ListTasks, SummariseTasks and AssessAttention: the clock is theirs, the rules are not."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from app.application.clock import today_utc
from app.application.task_query import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    OPEN_STATUSES,
    SignalCounts,
    TaskCounts,
    TaskFilter,
    TaskQuery,
    TaskScope,
    TaskSignal,
    TaskSort,
)
from app.application.use_cases.assess_attention import AssessAttention
from app.application.use_cases.list_tasks import ListTasks
from app.application.use_cases.summarise_tasks import SummariseTasks
from app.domain.attention import AttentionReason
from app.domain.project import DEFAULT_PROJECT_ID
from app.domain.task import TaskPriority, TaskStatus
from tests.auth_fakes import InMemoryUserRepository, a_user
from tests.builders import a_project, a_task
from tests.fakes import InMemoryProjectRepository, InMemoryTaskRepository

NOW = datetime(2026, 3, 10, 9, 30, tzinfo=UTC)
TODAY = date(2026, 3, 10)


def clock() -> datetime:
    return NOW


def due_in(days: int) -> date:
    return TODAY + timedelta(days=days)


@pytest.fixture
def tasks() -> InMemoryTaskRepository:
    return InMemoryTaskRepository(InMemoryUserRepository(), InMemoryProjectRepository())


@pytest.fixture
async def me(tasks: InMemoryTaskRepository) -> uuid.UUID:
    user = a_user()
    await tasks.users.add(user)
    return user.id


def test_today_is_the_utc_calendar_day_whatever_offset_the_clock_reports() -> None:
    almost_midnight_in_lisbon = datetime.fromisoformat("2026-03-10T23:30:00-01:00")

    assert today_utc(lambda: almost_midnight_in_lisbon) == date(2026, 3, 11)
    assert today_utc(clock) == TODAY


def test_a_query_defaults_to_the_design_view_open_tasks_by_urgency() -> None:
    query = TaskQuery()

    assert query.filter == TaskFilter()
    assert (
        query.filter.statuses
        == OPEN_STATUSES
        == {
            TaskStatus.TODO,
            TaskStatus.IN_PROGRESS,
            TaskStatus.TESTING,
        }
    )
    assert query.filter.scope is TaskScope.ALL
    assert query.sort is TaskSort.URGENCY
    assert (query.limit, query.offset) == (DEFAULT_LIMIT, 0) == (50, 0)
    assert MAX_LIMIT == 200


@pytest.mark.parametrize(("limit", "offset"), [(0, 0), (-1, 0), (MAX_LIMIT + 1, 0), (10, -1)])
def test_a_page_outside_the_bounds_is_refused(limit: int, offset: int) -> None:
    with pytest.raises(ValueError, match=r"limit|offset"):
        TaskQuery(limit=limit, offset=offset)


def test_my_tasks_needs_to_know_who_is_asking() -> None:
    with pytest.raises(ValueError, match="viewer_id"):
        TaskFilter(scope=TaskScope.MINE)


def test_a_filter_cannot_ask_for_an_assignee_and_for_nobody() -> None:
    with pytest.raises(ValueError, match="assignee"):
        TaskFilter(assignee_id=uuid.uuid4(), unassigned=True)


async def test_list_tasks_evaluates_dates_against_its_clock(
    tasks: InMemoryTaskRepository, me: uuid.UUID
) -> None:
    late = a_task(me, title="late", due_date=due_in(-1))
    calm = a_task(me, title="calm", due_date=due_in(30))
    for task in (late, calm):
        await tasks.add(task)
    overdue = TaskQuery(filter=TaskFilter(scope=TaskScope.OVERDUE))

    page = await ListTasks(tasks, clock=clock).execute(overdue)
    a_month_later = await ListTasks(tasks, clock=lambda: NOW + timedelta(days=31)).execute(overdue)

    assert [task.title for task in page.items] == ["late"]
    assert page.total == 1
    assert {task.title for task in a_month_later.items} == {"late", "calm"}


async def test_list_tasks_pages_through_the_urgency_order(
    tasks: InMemoryTaskRepository, me: uuid.UUID
) -> None:
    for days in (5, -2, 0, 40):
        await tasks.add(a_task(me, title=f"due {days}", due_date=due_in(days), assignee_id=me))
    list_tasks = ListTasks(tasks, clock=clock)

    first = await list_tasks.execute(TaskQuery(limit=3))
    rest = await list_tasks.execute(TaskQuery(limit=3, offset=3))

    assert [task.title for task in first.items] == ["due -2", "due 0", "due 5"]
    assert [task.title for task in rest.items] == ["due 40"]
    assert first.total == rest.total == 4


async def test_assess_attention_reads_today_from_its_clock(me: uuid.UUID) -> None:
    task = a_task(me, due_date=due_in(1), assignee_id=me)

    today = AssessAttention(clock=clock).execute(task)
    in_two_days = AssessAttention(clock=lambda: NOW + timedelta(days=2)).execute(task)

    assert (today.days_until_due, today.reasons) == (1, (AttentionReason.DUE_SOON,))
    assert (in_two_days.days_until_due, in_two_days.reasons) == (-1, (AttentionReason.OVERDUE,))


async def test_the_summary_counts_open_work_for_the_sidebar_and_the_attention_strip(
    tasks: InMemoryTaskRepository, me: uuid.UUID
) -> None:
    ballast = a_project(key="BT")
    await tasks.projects.add(ballast)
    stored = [
        a_task(me, project_id=ballast.id, due_date=due_in(-3), assignee_id=me),
        a_task(me, project_id=ballast.id, due_date=due_in(1), priority=TaskPriority.P0),
        a_task(me, due_date=due_in(0), assignee_id=me),
        a_task(me, due_date=due_in(-9), status=TaskStatus.DONE),
    ]
    for task in stored:
        await tasks.add(task)

    summary = await SummariseTasks(tasks, tasks.projects, clock=clock).execute(
        TaskFilter(), viewer_id=me
    )

    assert summary.counts == TaskCounts(all=3, mine=2, overdue=1)
    assert [(o.project.key, o.open_tasks) for o in summary.projects] == [("BT", 2), ("IN", 1)]
    assert summary.signals == SignalCounts(overdue=1, p0_at_risk=1, due_soon=2, needs_owner=1)


async def test_the_strip_follows_the_filters_but_never_the_status_or_the_selected_signal(
    tasks: InMemoryTaskRepository, me: uuid.UUID
) -> None:
    """Design line 726: the strip describes the open tasks in view. Choosing one of its
    chips, or looking at done tasks, must not blank the other chips."""
    ballast = a_project(key="BT")
    await tasks.projects.add(ballast)
    await tasks.add(a_task(me, project_id=ballast.id, due_date=due_in(-3), assignee_id=me))
    await tasks.add(a_task(me, due_date=due_in(0)))
    summarise = SummariseTasks(tasks, tasks.projects, clock=clock)

    in_project = await summarise.execute(TaskFilter(project_id=ballast.id), viewer_id=me)
    chip_chosen = await summarise.execute(
        TaskFilter(signal=TaskSignal.OVERDUE, statuses=frozenset({TaskStatus.DONE})),
        viewer_id=me,
    )

    assert in_project.signals == SignalCounts(overdue=1, p0_at_risk=0, due_soon=0, needs_owner=0)
    assert in_project.counts == TaskCounts(all=2, mine=1, overdue=1)
    assert chip_chosen.signals == SignalCounts(overdue=1, p0_at_risk=0, due_soon=1, needs_owner=1)
    assert DEFAULT_PROJECT_ID in {o.project.id for o in in_project.projects}
