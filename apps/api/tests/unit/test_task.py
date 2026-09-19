import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from app.domain.task import (
    DESCRIPTION_MAX_LENGTH,
    TITLE_MAX_LENGTH,
    InvalidTaskError,
    Task,
    TaskStatus,
)

CREATED = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
LATER = CREATED + timedelta(hours=3)
CREATOR = uuid.uuid4()


def new_task(**overrides: object) -> Task:
    arguments: dict[str, object] = {
        "task_id": uuid.uuid4(),
        "title": "Write the report",
        "created_by": CREATOR,
        "now": CREATED,
    }
    return Task.create(**(arguments | overrides))  # type: ignore[arg-type]


def test_a_new_task_starts_todo_unassigned_and_not_completed() -> None:
    task_id = uuid.uuid4()

    task = Task.create(task_id=task_id, title="Write the report", created_by=CREATOR, now=CREATED)

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


def test_a_new_task_keeps_its_optional_details() -> None:
    assignee = uuid.uuid4()

    task = new_task(description="Q1 numbers", due_date=date(2026, 2, 1), assignee_id=assignee)

    assert task.description == "Q1 numbers"
    assert task.due_date == date(2026, 2, 1)
    assert task.assignee_id == assignee


def test_status_values_are_the_public_vocabulary() -> None:
    assert [status.value for status in TaskStatus] == ["todo", "in_progress", "done"]


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


@pytest.mark.parametrize("status", [TaskStatus.TODO, TaskStatus.IN_PROGRESS])
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
        )
