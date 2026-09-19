"""The design's urgency model as an oracle, and the table of cases every port is held to.

``design_urgency`` is a line-by-line Python port of ``Component.urgency`` in the design
snapshot (``Ballast Tasks v2.dc.html``, lines 522 to 538, with ``soonWindow`` at its default
of 2). It is deliberately NOT the production code: ``app.domain.attention`` and the SQL
expression in the task repository are both compared against it over ``CASES``.
"""

import itertools
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from app.domain.task import Task, TaskPriority, TaskStatus

TODAY = date(2026, 3, 10)
NOW = datetime(2026, 3, 10, 9, 30, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class DesignUrgency:
    overdue: bool
    today: bool
    soon: bool
    critical: bool
    unassigned: bool
    score: float


def design_urgency(
    *, status: str, prio: int, importance: int, diff: int | None, assigned: bool
) -> DesignUrgency:
    is_open = status != "done"
    has = diff is not None
    days = diff if diff is not None else 0
    win = max(0, 2) + (2 if prio == 0 else 1 if prio == 1 else 0)
    overdue = is_open and has and days < 0
    today = is_open and has and days == 0
    soon = is_open and has and days > 0 and days <= win
    critical = is_open and has and prio == 0 and days >= 0 and days <= win
    unassigned = is_open and not assigned
    score: float = 0
    if overdue:
        score = 1000 + min(-days, 30) * 10
    elif critical:
        score = 800 + (win - days) * 10
    elif today:
        score = 600
    elif soon:
        score = 400 + (win - days) * 10
    elif is_open and has:
        score = max(0, 200 - days * 5)
    score += (40 if unassigned else 0) + importance / 10 + (3 - prio) * 3
    return DesignUrgency(overdue, today, soon, critical, unassigned, score)


@dataclass(frozen=True, slots=True)
class UrgencyCase:
    status: TaskStatus
    priority: TaskPriority
    importance: int
    diff: int | None
    assigned: bool

    @property
    def label(self) -> str:
        owner = "owned" if self.assigned else "unowned"
        return f"{self.status.value}-{self.priority.value}-i{self.importance}-d{self.diff}-{owner}"

    @property
    def expected(self) -> DesignUrgency:
        return design_urgency(
            status=self.status.value,
            prio=self.priority.rank,
            importance=self.importance,
            diff=self.diff,
            assigned=self.assigned,
        )

    def task(self, *, created_by: uuid.UUID, project_id: uuid.UUID, number: int) -> Task:
        return Task.create(
            task_id=uuid.uuid4(),
            title=self.label,
            created_by=created_by,
            project_id=project_id,
            key=f"UR-{number:02d}",
            status=self.status,
            priority=self.priority,
            importance=self.importance,
            due_date=None if self.diff is None else TODAY + timedelta(days=self.diff),
            assignee_id=created_by if self.assigned else None,
            now=NOW,
        )


# Every boundary of the model: far overdue (the 30-day cap), overdue, today, inside and just
# outside each priority's window (2, 3 and 4 days), the 40-day point where the distance
# score reaches zero, and no date at all.
_DIFFS = (None, -45, -30, -29, -1, 0, 1, 2, 3, 4, 5, 6, 7, 39, 40, 41, 365)

CASES = [
    UrgencyCase(status, priority, importance, diff, assigned)
    for status, priority, diff, assigned in itertools.product(
        TaskStatus, TaskPriority, _DIFFS, (True, False)
    )
    for importance in ((0, 50, 100) if diff in (None, 0, 3) else (55,))
]
