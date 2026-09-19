"""What a caller can ask of the task list: the design's filters, sorts and pages.

Plain values the use cases hand to the ``TaskRepository``; what each one MEANS is the design's
``Component.filtered`` (lines 540 to 572) and is pinned, adapter by adapter, by the task
repository contract suite. Nothing here knows the date: ``today`` travels next to the query.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from app.domain.task import Task, TaskPriority, TaskStatus

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
SEARCH_MAX_LENGTH = 200

# The design's "All open": every status except ``done``.
OPEN_STATUSES = frozenset(TaskStatus) - {TaskStatus.DONE}


class TaskScope(StrEnum):
    """The sidebar's three views."""

    ALL = "all"
    MINE = "mine"  # assigned to the viewer
    OVERDUE = "overdue"  # open and past its date


class DueFilter(StrEnum):
    OVERDUE = "overdue"  # open and past its date
    TODAY = "today"  # the date alone, done tasks included (design line 551)
    WEEK = "week"  # today and the six days after it, done tasks included (design line 552)
    NONE = "none"  # no date


class TaskSignal(StrEnum):
    """The four chips of the Attention strip (design lines 727 to 732)."""

    OVERDUE = "overdue"
    P0_AT_RISK = "p0_at_risk"
    DUE_SOON = "due_soon"
    NEEDS_OWNER = "needs_owner"


class TaskSort(StrEnum):
    """Every order ends newest first (``created_at``, then ``id``), so pages never overlap."""

    URGENCY = "urgency"  # app.domain.attention, highest first
    IMPORTANCE = "importance"  # highest first
    DUE_DATE = "due_date"  # earliest first, undated last, then the more important
    UPDATED = "updated"  # most recently updated first


@dataclass(frozen=True, slots=True)
class TaskFilter:
    """Every condition narrows the result; the default is the design's default view."""

    scope: TaskScope = TaskScope.ALL
    viewer_id: uuid.UUID | None = None  # who "mine" is
    project_id: uuid.UUID | None = None
    statuses: frozenset[TaskStatus] | None = OPEN_STATUSES  # None: everything
    due: DueFilter | None = None
    due_before: date | None = None  # on or before
    due_after: date | None = None  # on or after
    priorities: frozenset[TaskPriority] | None = None
    assignee_id: uuid.UUID | None = None
    unassigned: bool = False
    search: str | None = None  # case-insensitive, in the title or the description
    signal: TaskSignal | None = None

    def __post_init__(self) -> None:
        if self.scope is TaskScope.MINE and self.viewer_id is None:
            raise ValueError("viewer_id is required for the scope 'mine'")
        if self.unassigned and self.assignee_id is not None:
            raise ValueError("a filter names an assignee or asks for unassigned tasks, not both")


@dataclass(frozen=True, slots=True)
class TaskQuery:
    filter: TaskFilter = field(default_factory=TaskFilter)
    sort: TaskSort = TaskSort.URGENCY
    limit: int = DEFAULT_LIMIT
    offset: int = 0

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= MAX_LIMIT:
            raise ValueError(f"limit must be from 1 to {MAX_LIMIT}")
        if self.offset < 0:
            raise ValueError("offset must not be negative")


@dataclass(frozen=True, slots=True)
class TaskPage:
    items: Sequence[Task]
    total: int  # how many tasks match the filter, whatever the page


@dataclass(frozen=True, slots=True)
class TaskCounts:
    """The sidebar: open tasks in the whole workspace (design line 743)."""

    all: int
    mine: int
    overdue: int


@dataclass(frozen=True, slots=True)
class SignalCounts:
    overdue: int
    p0_at_risk: int
    due_soon: int
    needs_owner: int
