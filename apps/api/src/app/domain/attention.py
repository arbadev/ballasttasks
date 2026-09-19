"""What about a task asks for attention today: the design's one urgency model.

A port of ``Component.dueInfo`` and ``Component.urgency`` in the design snapshot
(``Ballast Tasks v2.dc.html``, lines 509 to 538). The design uses it for every surface (rows,
cards, the Attention strip, the panel banner and the default sort), and so does the API: the
task repository's SQL ordering is held to this module by a table of cases.

Standard library only, and no clock: ``today`` is always an argument. It is a UTC calendar
day (see "Time" in ``docs/architecture.md``).
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from app.domain.task import Task, TaskPriority

# The design's ``soonWindow`` prop, at its default (design line 524).
SOON_WINDOW_DAYS = 2
# "Due in the next 7 days" is ``0 <= days < 7`` (``inWeek``, design lines 515 to 517).
WEEK_DAYS = 7
OVERDUE_DAYS_CAP = 30


class AttentionReason(StrEnum):
    """Machine-readable, most severe first. ``due_today`` and ``due_soon`` exclude each other."""

    OVERDUE = "overdue"
    P0_AT_RISK = "p0_at_risk"
    DUE_TODAY = "due_today"
    DUE_SOON = "due_soon"
    NEEDS_OWNER = "needs_owner"


@dataclass(frozen=True, slots=True)
class Attention:
    is_overdue: bool
    # The design's "due soon" signal: not overdue, and due today or inside the window.
    is_due_soon: bool
    is_p0_at_risk: bool
    needs_owner: bool
    days_until_due: int | None
    urgency: float
    reasons: tuple[AttentionReason, ...]


def days_until(due_date: date | None, *, today: date) -> int | None:
    """Whole calendar days from ``today``; negative when the date has passed."""
    return None if due_date is None else (due_date - today).days


def soon_window(priority: TaskPriority) -> int:
    """How many days ahead "soon" reaches: P0 looks 2 days further, P1 one (design line 524)."""
    return SOON_WINDOW_DAYS + {TaskPriority.P0: 2, TaskPriority.P1: 1}.get(priority, 0)


def assess(task: Task, *, today: date) -> Attention:
    days = days_until(task.due_date, today=today)
    window = soon_window(task.priority)
    # The date rules look only at open tasks that have a date (``open && has`` in the design).
    left = days if task.is_open else None
    overdue = left is not None and left < 0
    due_today = left == 0
    soon = left is not None and 0 < left <= window
    at_risk = (due_today or soon) and task.priority is TaskPriority.P0
    needs_owner = task.is_open and task.assignee_id is None
    # Design line 536: an open task nobody owns, then importance, then priority.
    score = (
        _date_score(left, window=window, at_risk=at_risk)
        + (40 if needs_owner else 0)
        + task.importance / 10
        + (3 - task.priority.rank) * 3
    )

    flags = (
        (overdue, AttentionReason.OVERDUE),
        (at_risk, AttentionReason.P0_AT_RISK),
        (due_today, AttentionReason.DUE_TODAY),
        (soon, AttentionReason.DUE_SOON),
        (needs_owner, AttentionReason.NEEDS_OWNER),
    )
    return Attention(
        is_overdue=overdue,
        is_due_soon=due_today or soon,
        is_p0_at_risk=at_risk,
        needs_owner=needs_owner,
        days_until_due=days,
        urgency=score,
        reasons=tuple(reason for applies, reason in flags if applies),
    )


def _date_score(left: int | None, *, window: int, at_risk: bool) -> int:
    """Design lines 531 to 535: the first branch that applies gives the base score."""
    if left is None:
        return 0
    if left < 0:
        return 1000 + min(-left, OVERDUE_DAYS_CAP) * 10
    if at_risk:
        return 800 + (window - left) * 10
    if left == 0:
        return 600
    if left <= window:
        return 400 + (window - left) * 10
    return max(0, 200 - left * 5)
