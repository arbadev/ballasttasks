"""What a ``log`` entry says: the design's words, in one place.

The design's script writes a line into a task's activity through ``update(id, patch,
logText)`` and its create and accept paths. Where it does, the text here is the design's,
character for character (the line of the snapshot is named). Where the design changes a
task silently but this API logs the event, the text is written in the same voice and marked
"not in the design". Nothing outside this module spells a log line (ADR 0007).

Standard library only, and no clock: ``today`` is handed in.
"""

from datetime import date, timedelta

from app.domain.task import Task, TaskPriority, TaskStatus

# Line 582, ``create``.
CREATED = "Created the task"
# Line 704, the assignee picker set to nobody.
UNASSIGNED = "Unassigned"
# Line 493: how the design names somebody it cannot find.
UNKNOWN_PERSON = "Unknown"

# Line 411: the names of the four columns.
STATUS_NAMES = {
    TaskStatus.TODO: "To Do",
    TaskStatus.IN_PROGRESS: "In Progress",
    TaskStatus.TESTING: "Testing",
    TaskStatus.DONE: "Done",
}

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_WEEK = timedelta(days=7)


def moved(old: TaskStatus, new: TaskStatus) -> str:
    """Line 578, ``move``. Completing and reopening are moves too (line 579, ``toggleDone``)."""
    return f"Moved {STATUS_NAMES[old]} → {STATUS_NAMES[new]}"


def assigned_to(full_name: str) -> str:
    """Lines 677 and 704."""
    return f"Assigned to {full_name}"


def due_date_changed(old: date | None, new: date | None, *, today: date) -> str:
    """The design logs a due date only from its two quick actions, in relative words:
    ``dueTomorrow`` (line 678) and ``dueNextWeek`` (line 679, a week after the due date when
    that is still ahead, otherwise a week after today). A change that is exactly one of them
    reads as the design does. Not in the design: any other date, printed the way the design
    prints dates (``Sep 4``, line 513), and the date being cleared.
    """
    if new is None:
        return "Due date cleared"
    if new == today + timedelta(days=1):
        return "Due date moved to tomorrow"
    week_from = old if old is not None and old > today else today
    if new == week_from + _WEEK:
        return "Due date moved a week out"
    year = "" if new.year == today.year else f", {new.year}"
    return f"Due date moved to {_MONTHS[new.month - 1]} {new.day}{year}"


def priority_changed(old: TaskPriority, new: TaskPriority) -> str:
    """Not in the design (line 706 changes the priority silently); shaped like ``moved``."""
    return f"Priority {old.value} → {new.value}"


def step_added(title: str) -> str:
    """Not in the design (``addStep``, line 585, logs nothing)."""
    return f"Added step “{title}”"


def step_completed(title: str) -> str:
    """Not in the design (line 689 ticks a step silently)."""
    return f"Completed step “{title}”"


def steps_drafted(count: int, *, added_by: str) -> str:
    """Line 626, ``accept``: several steps taken at once, and the first name of who took them."""
    first_name = added_by.split()[0] if added_by.split() else UNKNOWN_PERSON
    return f"Drafted {count} step{'' if count == 1 else 's'} · added by {first_name}"


def changes(before: Task, after: Task, *, today: date, assignee_name: str | None) -> list[str]:
    """The lines a change to a task leaves, in a fixed order; none when nothing logged changed.

    Title, description, importance and project are edited silently, as in the design (lines
    683, 684, 707 and 708). ``assignee_name`` is the full name of ``after``'s assignee.
    """
    lines: list[str] = []
    if after.status is not before.status:
        lines.append(moved(before.status, after.status))
    if after.assignee_id != before.assignee_id:
        lines.append(
            UNASSIGNED
            if after.assignee_id is None
            else assigned_to(assignee_name or UNKNOWN_PERSON)
        )
    if after.due_date != before.due_date:
        lines.append(due_date_changed(before.due_date, after.due_date, today=today))
    if after.priority is not before.priority:
        lines.append(priority_changed(before.priority, after.priority))
    return lines
