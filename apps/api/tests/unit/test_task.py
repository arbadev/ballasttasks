import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from app.domain.task import (
    DEFAULT_IMPORTANCE,
    DEFAULT_PRIORITY,
    DESCRIPTION_MAX_LENGTH,
    TITLE_MAX_LENGTH,
    InvalidTaskError,
    Task,
    TaskPriority,
    TaskStatus,
)

CREATED = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
LATER = CREATED + timedelta(hours=3)
CREATOR = uuid.uuid4()
PROJECT = uuid.uuid4()


def new_task(**overrides: object) -> Task:
    arguments: dict[str, object] = {
        "task_id": uuid.uuid4(),
        "title": "Write the report",
        "created_by": CREATOR,
        "project_id": PROJECT,
        "key": "BT-04",
        "now": CREATED,
    }
    return Task.create(**(arguments | overrides))  # type: ignore[arg-type]


def test_a_new_task_starts_todo_unassigned_and_not_completed() -> None:
    task_id = uuid.uuid4()

    task = Task.create(
        task_id=task_id,
        title="Write the report",
        created_by=CREATOR,
        project_id=PROJECT,
        key="BT-04",
        now=CREATED,
    )

    assert task.id == task_id
    assert task.title == "Write the report"
    assert task.description is None
    assert task.status is TaskStatus.TODO
    assert task.due_date is None
    assert task.created_by == CREATOR
    assert task.assignee_id is None
    assert task.created_at == CREATED
    assert task.updated_at == CREATED
    assert task.completed_at is None
    assert task.project_id == PROJECT
    assert task.key == "BT-04"
    assert task.priority is DEFAULT_PRIORITY is TaskPriority.P2
    assert task.importance == DEFAULT_IMPORTANCE == 50
    assert task.is_open


def test_a_new_task_keeps_its_optional_details() -> None:
    assignee = uuid.uuid4()

    task = new_task(description="Q1 numbers", due_date=date(2026, 2, 1), assignee_id=assignee)

    assert task.description == "Q1 numbers"
    assert task.due_date == date(2026, 2, 1)
    assert task.assignee_id == assignee


def test_status_values_are_the_public_vocabulary() -> None:
    assert [status.value for status in TaskStatus] == [
        "todo",
        "in_progress",
        "testing",
        "done",
    ]


def test_title_is_stored_without_surrounding_whitespace() -> None:
    assert new_task(title="  Write the report \n").title == "Write the report"


@pytest.mark.parametrize("title", ["", "   ", "\t\n"])
def test_a_blank_title_is_rejected(title: str) -> None:
    with pytest.raises(InvalidTaskError, match="title"):
        new_task(title=title)


def test_title_length_is_bounded() -> None:
    assert new_task(title="x" * TITLE_MAX_LENGTH).title == "x" * TITLE_MAX_LENGTH

    with pytest.raises(InvalidTaskError, match=str(TITLE_MAX_LENGTH)):
        new_task(title="x" * (TITLE_MAX_LENGTH + 1))


def test_description_length_is_bounded() -> None:
    with pytest.raises(InvalidTaskError, match=str(DESCRIPTION_MAX_LENGTH)):
        new_task(description="x" * (DESCRIPTION_MAX_LENGTH + 1))


def test_a_nul_character_is_rejected_in_the_title_and_the_description() -> None:
    with pytest.raises(InvalidTaskError, match="title"):
        new_task(title="Write\x00the report")
    with pytest.raises(InvalidTaskError, match="description"):
        new_task(description="Q1\x00numbers")


def test_retitle_and_describe_reject_a_nul_character() -> None:
    task = new_task()

    with pytest.raises(InvalidTaskError, match="title"):
        task.retitle("Write\x00the report", now=LATER)
    with pytest.raises(InvalidTaskError, match="description"):
        task.describe("Q1\x00numbers", now=LATER)

    assert task == new_task(task_id=task.id)


def test_timestamps_must_be_timezone_aware() -> None:
    with pytest.raises(InvalidTaskError, match="timezone"):
        new_task(now=datetime(2026, 1, 5, 9, 0))


def test_retitle_applies_the_title_rules_and_touches_updated_at() -> None:
    task = new_task()

    task.retitle("  Publish the report ", now=LATER)

    assert task.title == "Publish the report"
    assert task.updated_at == LATER
    assert task.created_at == CREATED


def test_a_rejected_retitle_leaves_the_task_unchanged() -> None:
    task = new_task()

    with pytest.raises(InvalidTaskError):
        task.retitle("   ", now=LATER)

    assert task.title == "Write the report"
    assert task.updated_at == CREATED


def test_describe_sets_and_clears_the_description() -> None:
    task = new_task()

    task.describe("Q1 numbers", now=LATER)
    assert task.description == "Q1 numbers"
    assert task.updated_at == LATER

    task.describe(None, now=LATER)
    assert task.description is None

    with pytest.raises(InvalidTaskError):
        task.describe("x" * (DESCRIPTION_MAX_LENGTH + 1), now=LATER)


def test_reschedule_sets_and_clears_the_due_date() -> None:
    task = new_task()

    task.reschedule(date(2026, 3, 1), now=LATER)
    assert task.due_date == date(2026, 3, 1)
    assert task.updated_at == LATER

    task.reschedule(None, now=LATER)
    assert task.due_date is None


def test_assign_to_sets_and_clears_the_assignee() -> None:
    task = new_task()
    assignee = uuid.uuid4()

    task.assign_to(assignee, now=LATER)
    assert task.assignee_id == assignee
    assert task.updated_at == LATER

    task.assign_to(None, now=LATER)
    assert task.assignee_id is None


def test_moving_to_done_sets_completed_at() -> None:
    task = new_task()

    task.move_to(TaskStatus.DONE, now=LATER)

    assert task.status is TaskStatus.DONE
    assert task.completed_at == LATER
    assert task.updated_at == LATER


def test_moving_to_in_progress_does_not_complete_the_task() -> None:
    task = new_task()

    task.move_to(TaskStatus.IN_PROGRESS, now=LATER)

    assert task.status is TaskStatus.IN_PROGRESS
    assert task.completed_at is None


@pytest.mark.parametrize("status", [TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.TESTING])
def test_leaving_done_clears_completed_at(status: TaskStatus) -> None:
    task = new_task()
    task.move_to(TaskStatus.DONE, now=LATER)

    task.move_to(status, now=LATER + timedelta(hours=1))

    assert task.status is status
    assert task.completed_at is None


def test_marking_a_done_task_done_again_keeps_the_first_completion_time() -> None:
    task = new_task()
    task.move_to(TaskStatus.DONE, now=LATER)

    task.move_to(TaskStatus.DONE, now=LATER + timedelta(days=1))

    assert task.completed_at == LATER


def test_a_stored_task_that_breaks_the_completion_rule_cannot_be_rebuilt() -> None:
    with pytest.raises(InvalidTaskError, match="completed_at"):
        Task(
            id=uuid.uuid4(),
            title="Write the report",
            description=None,
            status=TaskStatus.TODO,
            due_date=None,
            created_by=CREATOR,
            assignee_id=None,
            created_at=CREATED,
            updated_at=CREATED,
            completed_at=LATER,
            project_id=PROJECT,
            key="BT-04",
            priority=TaskPriority.P2,
            importance=50,
        )


# --- the design's model: four statuses, priority, importance, project and key ----------------


def test_moving_to_testing_keeps_the_task_open() -> None:
    task = new_task()

    task.move_to(TaskStatus.TESTING, now=LATER)

    assert task.status is TaskStatus.TESTING
    assert task.completed_at is None
    assert task.is_open


def test_a_done_task_is_not_open() -> None:
    task = new_task()
    task.move_to(TaskStatus.DONE, now=LATER)

    assert not task.is_open


def test_a_task_can_be_created_in_any_status_and_done_is_completed_at_once() -> None:
    assert new_task(status=TaskStatus.TESTING).status is TaskStatus.TESTING

    done = new_task(status=TaskStatus.DONE)

    assert done.status is TaskStatus.DONE
    assert done.completed_at == CREATED


def test_priorities_are_p0_to_p3_and_rank_from_most_to_least_urgent() -> None:
    assert [priority.value for priority in TaskPriority] == ["P0", "P1", "P2", "P3"]
    assert [priority.rank for priority in TaskPriority] == [0, 1, 2, 3]
    assert [TaskPriority.from_rank(rank) for rank in range(4)] == list(TaskPriority)
    with pytest.raises(ValueError, match="4"):
        TaskPriority.from_rank(4)


def test_prioritise_changes_the_priority_and_touches_updated_at() -> None:
    task = new_task(priority=TaskPriority.P3)
    assert task.priority is TaskPriority.P3

    task.prioritise(TaskPriority.P0, now=LATER)

    assert task.priority is TaskPriority.P0
    assert task.updated_at == LATER


@pytest.mark.parametrize("importance", [0, 1, 50, 100])
def test_importance_runs_from_0_to_100(importance: int) -> None:
    assert new_task(importance=importance).importance == importance


@pytest.mark.parametrize("importance", [-1, 101, 1000])
def test_importance_outside_0_to_100_is_rejected(importance: int) -> None:
    with pytest.raises(InvalidTaskError, match="importance"):
        new_task(importance=importance)


@pytest.mark.parametrize("importance", [True, 50.0, "50"])
def test_importance_must_be_a_whole_number(importance: object) -> None:
    with pytest.raises(InvalidTaskError, match="importance"):
        new_task(importance=importance)


def test_weigh_changes_the_importance_or_leaves_the_task_unchanged() -> None:
    task = new_task()

    task.weigh(95, now=LATER)
    assert task.importance == 95
    assert task.updated_at == LATER

    with pytest.raises(InvalidTaskError, match="importance"):
        task.weigh(101, now=LATER + timedelta(hours=1))
    assert task.importance == 95
    assert task.updated_at == LATER


def test_moving_to_another_project_keeps_the_key() -> None:
    task = new_task()
    elsewhere = uuid.uuid4()

    task.move_to_project(elsewhere, now=LATER)

    assert task.project_id == elsewhere
    assert task.key == "BT-04"
    assert task.updated_at == LATER


@pytest.mark.parametrize("key", ["", "BT", "bt-04", "BT-4", "BT-00", "B-04", "BT-04 "])
def test_a_key_that_is_not_in_canonical_form_is_rejected(key: str) -> None:
    with pytest.raises(InvalidTaskError, match="key"):
        new_task(key=key)
