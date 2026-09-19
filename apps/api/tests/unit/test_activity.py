"""The activity entry, and the words the design writes into a task's timeline.

Where the design's script logs an event, the expected text below is copied from it (the line
is named); the rest is the wording this API adds in the same voice (ADR 0007).
"""

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from app.domain import activity_log
from app.domain.activity import (
    ACTIVITY_TEXT_MAX_LENGTH,
    ActivityEntry,
    ActivityKind,
    Actor,
    InvalidActivityError,
)
from app.domain.task import Task, TaskPriority, TaskStatus

NOW = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
TODAY = NOW.date()
TASK = uuid.uuid4()
ACTOR = uuid.uuid4()


def test_a_log_entry_keeps_what_it_is_given() -> None:
    entry_id = uuid.uuid4()

    entry = ActivityEntry.log(
        entry_id=entry_id, task_id=TASK, actor_id=ACTOR, text="Created the task", now=NOW
    )

    assert entry == ActivityEntry(
        id=entry_id,
        task_id=TASK,
        kind=ActivityKind.LOG,
        text="Created the task",
        actor_id=ACTOR,
        created_at=NOW,
    )


def test_a_comment_is_trimmed() -> None:
    entry = ActivityEntry.comment(
        entry_id=uuid.uuid4(), task_id=TASK, actor_id=ACTOR, text="  Looks good \n", now=NOW
    )

    assert entry.kind is ActivityKind.COMMENT
    assert entry.text == "Looks good"


@pytest.mark.parametrize("make", [ActivityEntry.log, ActivityEntry.comment])
@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "blank"),
        (" \n\t", "blank"),
        ("x" * (ACTIVITY_TEXT_MAX_LENGTH + 1), "at most 2000"),
        ("before\x00after", "NUL"),
    ],
)
def test_text_that_cannot_be_stored_is_refused(make: object, text: str, message: str) -> None:
    with pytest.raises(InvalidActivityError, match=message):
        make(entry_id=uuid.uuid4(), task_id=TASK, actor_id=ACTOR, text=text, now=NOW)  # type: ignore[operator]


def test_the_longest_text_is_measured_after_trimming() -> None:
    entry = ActivityEntry.comment(
        entry_id=uuid.uuid4(),
        task_id=TASK,
        actor_id=ACTOR,
        text=" " + "x" * ACTIVITY_TEXT_MAX_LENGTH + " ",
        now=NOW,
    )

    assert len(entry.text) == ACTIVITY_TEXT_MAX_LENGTH


def test_a_naive_timestamp_is_refused() -> None:
    with pytest.raises(InvalidActivityError, match="timezone-aware"):
        ActivityEntry.log(
            entry_id=uuid.uuid4(),
            task_id=TASK,
            actor_id=ACTOR,
            text="Created the task",
            now=datetime(2026, 1, 5, 9, 0),
        )


def test_an_entry_cannot_be_changed() -> None:
    entry = ActivityEntry.log(
        entry_id=uuid.uuid4(), task_id=TASK, actor_id=ACTOR, text="Created the task", now=NOW
    )

    with pytest.raises(AttributeError):
        entry.text = "Something else"  # type: ignore[misc]


def test_an_actor_has_initials_and_nothing_private() -> None:
    actor = Actor(id=ACTOR, full_name="Lucía Marín")

    assert actor.initials == "LM"
    assert not hasattr(actor, "email")


# --- the design's words -------------------------------------------------------------------


def test_created_is_the_design_s_first_entry() -> None:
    # design line 582: activity: [{ type: 'log', who: 'ab', text: 'Created the task', ... }]
    assert activity_log.CREATED == "Created the task"


@pytest.mark.parametrize(
    ("old", "new", "text"),
    [
        # design line 578, with the column names of line 411; the seed data (lines 430 to 477)
        # shows the same sentences.
        (TaskStatus.TODO, TaskStatus.IN_PROGRESS, "Moved To Do → In Progress"),
        (TaskStatus.IN_PROGRESS, TaskStatus.TESTING, "Moved In Progress → Testing"),
        (TaskStatus.TESTING, TaskStatus.DONE, "Moved Testing → Done"),
        # toggleDone (line 579): completing and reopening are moves like any other.
        (TaskStatus.IN_PROGRESS, TaskStatus.DONE, "Moved In Progress → Done"),
        (TaskStatus.DONE, TaskStatus.TODO, "Moved Done → To Do"),
    ],
)
def test_a_move_names_both_columns(old: TaskStatus, new: TaskStatus, text: str) -> None:
    assert activity_log.moved(old, new) == text


def test_every_status_has_a_column_name() -> None:
    assert set(activity_log.STATUS_NAMES) == set(TaskStatus)


def test_assignment_names_the_person() -> None:
    # design lines 677 and 704
    assert activity_log.assigned_to("Andres Barradas") == "Assigned to Andres Barradas"
    assert activity_log.UNASSIGNED == "Unassigned"


@pytest.mark.parametrize(
    ("old", "new", "text"),
    [
        # design line 678, dueTomorrow
        (None, TODAY + timedelta(days=1), "Due date moved to tomorrow"),
        (TODAY + timedelta(days=9), TODAY + timedelta(days=1), "Due date moved to tomorrow"),
        # design line 679, dueNextWeek: a week after the due date when that is still ahead,
        # otherwise a week after today.
        (None, TODAY + timedelta(days=7), "Due date moved a week out"),
        (TODAY - timedelta(days=3), TODAY + timedelta(days=7), "Due date moved a week out"),
        (TODAY, TODAY + timedelta(days=7), "Due date moved a week out"),
        (TODAY + timedelta(days=2), TODAY + timedelta(days=9), "Due date moved a week out"),
        # Not in the design (its date field logs nothing): the date as the design prints one.
        (TODAY + timedelta(days=2), TODAY + timedelta(days=7), "Due date moved to Jan 12"),
        (None, date(2026, 9, 4), "Due date moved to Sep 4"),
        (None, TODAY, "Due date moved to Jan 5"),
        (None, date(2027, 2, 14), "Due date moved to Feb 14, 2027"),
        (TODAY + timedelta(days=2), None, "Due date cleared"),
    ],
)
def test_a_due_date_change_reads_as_the_design_s_quick_actions_where_it_is_one(
    old: date | None, new: date | None, text: str
) -> None:
    assert activity_log.due_date_changed(old, new, today=TODAY) == text


def test_a_priority_change_names_both_priorities() -> None:
    assert activity_log.priority_changed(TaskPriority.P2, TaskPriority.P0) == "Priority P2 → P0"


def test_steps_are_quoted_by_title() -> None:
    assert activity_log.step_added("Write the test") == "Added step “Write the test”"
    assert activity_log.step_completed("Write the test") == "Completed step “Write the test”"


@pytest.mark.parametrize(
    ("count", "full_name", "text"),
    [
        # design line 626: `Drafted ${n} step${n === 1 ? '' : 's'} · added by Andres`
        (1, "Andres Barradas", "Drafted 1 step · added by Andres"),
        (6, "Andres Barradas", "Drafted 6 steps · added by Andres"),
        (2, "Cher", "Drafted 2 steps · added by Cher"),
    ],
)
def test_steps_accepted_in_bulk_say_how_many_and_who_added_them(
    count: int, full_name: str, text: str
) -> None:
    assert activity_log.steps_drafted(count, added_by=full_name) == text


# --- update(id, patch, logText): what a change to a task leaves in the log ------------------


def a_task(**overrides: object) -> Task:
    arguments: dict[str, object] = {
        "task_id": TASK,
        "title": "Write the report",
        "created_by": ACTOR,
        "project_id": uuid.uuid4(),
        "key": "BT-04",
        "now": NOW,
    }
    return Task.create(**(arguments | overrides))  # type: ignore[arg-type]


def test_a_change_that_alters_nothing_leaves_nothing() -> None:
    task = a_task(due_date=TODAY, assignee_id=ACTOR)

    assert activity_log.changes(task, replace(task), today=TODAY, assignee_name="Ada") == []


def test_fields_the_design_edits_silently_leave_nothing() -> None:
    # design lines 683, 684, 707, 708: title, description, importance and project carry no text.
    before = a_task()
    after = replace(
        before, title="Another", description="More", importance=90, project_id=uuid.uuid4()
    )

    assert activity_log.changes(before, after, today=TODAY, assignee_name=None) == []


def test_every_logged_field_leaves_its_own_line_in_a_fixed_order() -> None:
    before = a_task()
    after = replace(
        before,
        status=TaskStatus.DONE,
        completed_at=NOW,
        assignee_id=uuid.uuid4(),
        due_date=TODAY + timedelta(days=1),
        priority=TaskPriority.P0,
    )

    assert activity_log.changes(before, after, today=TODAY, assignee_name="Lucía Marín") == [
        "Moved To Do → Done",
        "Assigned to Lucía Marín",
        "Due date moved to tomorrow",
        "Priority P2 → P0",
    ]


def test_clearing_the_assignee_is_unassigned() -> None:
    before = a_task(assignee_id=ACTOR)
    after = replace(before, assignee_id=None)

    assert activity_log.changes(before, after, today=TODAY, assignee_name=None) == ["Unassigned"]


def test_an_assignee_nobody_can_name_is_unknown_as_in_the_design() -> None:
    # design line 493: person(id) falls back to { name: 'Unknown' }
    before = a_task()
    after = replace(before, assignee_id=uuid.uuid4())

    assert activity_log.changes(before, after, today=TODAY, assignee_name=None) == [
        "Assigned to Unknown"
    ]
