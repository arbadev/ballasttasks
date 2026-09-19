"""The design's date rules, filters and orders as SQL, so they run in PostgreSQL.

This is ``app.domain.attention`` and the design's ``Component.filtered`` (design lines 509 to
572) once more, in SQL, and nothing here may drift from them:

- the numbers: ``tests/integration/test_urgency_sql.py`` compares ``urgency_score`` and every
  signal with the design's own function over a table of cases;
- the filters and orders: ``tests/contract/test_task_repository_contract.py`` runs the same
  expectations against this adapter and the in-memory fake, which uses the domain module.

``today`` is always a bound parameter, never ``CURRENT_DATE``: the clock belongs to the
application, and a test pins it.
"""

from datetime import date
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Date,
    Integer,
    Numeric,
    and_,
    case,
    cast,
    func,
    literal,
    literal_column,
    or_,
    type_coerce,
)

from app.application.task_query import (
    OPEN_STATUSES,
    DueFilter,
    TaskFilter,
    TaskScope,
    TaskSignal,
    TaskSort,
)
from app.domain.attention import OVERDUE_DAYS_CAP, SOON_WINDOW_DAYS, WEEK_DAYS
from app.domain.task import TaskPriority, TaskStatus
from app.infrastructure.db.models.task import TaskModel

# A literal, not a bound parameter: it is the predicate of the partial index
# ``ix_tasks_open_project_id_due_date``, and the planner only matches what it can read.
IS_OPEN: ColumnElement[bool] = TaskModel.status != literal_column(f"'{TaskStatus.DONE.value}'")

_P0, _P1 = TaskPriority.P0.rank, TaskPriority.P1.rank
# P0 looks two days further ahead, P1 one (design line 524).
_WINDOW = case(
    (TaskModel.priority == _P0, SOON_WINDOW_DAYS + 2),
    (TaskModel.priority == _P1, SOON_WINDOW_DAYS + 1),
    else_=SOON_WINDOW_DAYS,
)
# The date rules look only at open tasks that have a date (``open && has`` in the design).
_DATED = and_(IS_OPEN, TaskModel.due_date.is_not(None))
_NEEDS_OWNER = and_(IS_OPEN, TaskModel.assignee_id.is_(None))


def _days(today: date) -> ColumnElement[int]:
    """Whole calendar days until the due date; in PostgreSQL ``date - date`` is an integer."""
    return type_coerce(TaskModel.due_date - literal(today, type_=Date), Integer)


def _overdue(today: date) -> ColumnElement[bool]:
    return and_(_DATED, _days(today) < 0)


def _due_today(today: date) -> ColumnElement[bool]:
    return and_(_DATED, _days(today) == 0)


def _soon(today: date) -> ColumnElement[bool]:
    return and_(_DATED, _days(today) > 0, _days(today) <= _WINDOW)


def _p0_at_risk(today: date) -> ColumnElement[bool]:
    days = _days(today)
    return and_(_DATED, TaskModel.priority == _P0, days >= 0, days <= _WINDOW)


def signal_condition(signal: TaskSignal, today: date) -> ColumnElement[bool]:
    """The four chips of the Attention strip (design lines 727 to 732)."""
    if signal is TaskSignal.OVERDUE:
        return _overdue(today)
    if signal is TaskSignal.P0_AT_RISK:
        return _p0_at_risk(today)
    if signal is TaskSignal.DUE_SOON:
        return or_(_due_today(today), _soon(today))
    return _NEEDS_OWNER


def urgency_score(today: date) -> ColumnElement[float]:
    """``Component.urgency`` (design lines 531 to 536): the first branch that applies gives
    the base score, then ownership, importance and priority are added. ``numeric``, so equal
    scores are exactly equal and the tie-break decides."""
    days = _days(today)
    base = case(
        (_overdue(today), 1000 + func.least(-days, OVERDUE_DAYS_CAP) * 10),
        (_p0_at_risk(today), 800 + (_WINDOW - days) * 10),
        (_due_today(today), 600),
        (_soon(today), 400 + (_WINDOW - days) * 10),
        (_DATED, func.greatest(0, 200 - days * 5)),
        else_=0,
    )
    return (
        base
        + case((_NEEDS_OWNER, 40), else_=0)
        + cast(TaskModel.importance, Numeric) / 10
        + (3 - TaskModel.priority) * 3
    )


def conditions(task_filter: TaskFilter, today: date) -> list[ColumnElement[bool]]:
    """One clause per condition of the filter; all of them must hold."""
    f = task_filter
    days = _days(today)
    clauses: list[ColumnElement[bool]] = []
    if f.project_id is not None:
        clauses.append(TaskModel.project_id == f.project_id)
    if f.scope is TaskScope.MINE:
        clauses.append(TaskModel.assignee_id == f.viewer_id)
    if f.scope is TaskScope.OVERDUE or f.due is DueFilter.OVERDUE:
        clauses.append(_overdue(today))
    if f.statuses == OPEN_STATUSES:
        clauses.append(IS_OPEN)
    elif f.statuses is not None:
        clauses.append(TaskModel.status.in_(sorted(status.value for status in f.statuses)))
    # "today" and "week" look at the date alone, done tasks included (design lines 551, 552).
    if f.due is DueFilter.TODAY:
        clauses.append(days == 0)
    elif f.due is DueFilter.WEEK:
        clauses.append(and_(days >= 0, days < WEEK_DAYS))
    elif f.due is DueFilter.NONE:
        clauses.append(TaskModel.due_date.is_(None))
    if f.due_before is not None:
        clauses.append(TaskModel.due_date <= f.due_before)
    if f.due_after is not None:
        clauses.append(TaskModel.due_date >= f.due_after)
    if f.priorities is not None:
        clauses.append(TaskModel.priority.in_(sorted(p.rank for p in f.priorities)))
    if f.unassigned:
        clauses.append(TaskModel.assignee_id.is_(None))
    if f.assignee_id is not None:
        clauses.append(TaskModel.assignee_id == f.assignee_id)
    if f.search is not None:
        # autoescape: "%" and "_" in what the user typed are text, not wildcards.
        clauses.append(
            or_(
                TaskModel.title.icontains(f.search, autoescape=True),
                TaskModel.description.icontains(f.search, autoescape=True),
            )
        )
    if f.signal is not None:
        clauses.append(signal_condition(f.signal, today))
    return clauses


def ordering(sort: TaskSort, today: date) -> list[ColumnElement[Any]]:
    """Every order ends newest first (``created_at``, then ``id``), so pages never overlap."""
    newest_first: list[ColumnElement[Any]] = [TaskModel.created_at.desc(), TaskModel.id.desc()]
    if sort is TaskSort.URGENCY:
        return [urgency_score(today).desc(), *newest_first]
    if sort is TaskSort.IMPORTANCE:
        return [TaskModel.importance.desc(), *newest_first]
    if sort is TaskSort.DUE_DATE:
        return [
            TaskModel.due_date.asc().nulls_last(),
            TaskModel.importance.desc(),
            *newest_first,
        ]
    return [TaskModel.updated_at.desc(), *newest_first]
