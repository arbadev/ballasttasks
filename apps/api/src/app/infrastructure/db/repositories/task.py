import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.errors import (
    InvalidAssigneeError,
    StoredTaskInvalid,
    TaskNotFound,
    UnknownProjectError,
)
from app.application.task_query import (
    SignalCounts,
    TaskCounts,
    TaskFilter,
    TaskPage,
    TaskQuery,
    TaskSignal,
    every_status,
)
from app.domain.task import InvalidTaskError, Task, TaskPriority, TaskStatus
from app.domain.task_key import TaskKey
from app.infrastructure.db.constraints import violated_constraint
from app.infrastructure.db.models.task import ASSIGNEE_FOREIGN_KEY, PROJECT_FOREIGN_KEY, TaskModel
from app.infrastructure.db.repositories.task_queries import (
    IS_OPEN,
    conditions,
    ordering,
    signal_condition,
)

_FIELDS = (
    "title",
    "description",
    "due_date",
    "created_by",
    "assignee_id",
    "created_at",
    "updated_at",
    "completed_at",
    "project_id",
    "key",
    "importance",
)


class SqlAlchemyTaskRepository:
    """TaskRepository on PostgreSQL.

    Works inside the session it is given and never commits: the transaction belongs to
    ``transactional_session`` (see ``app.infrastructure.db.unit_of_work``).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, task: Task) -> None:
        async with self._refusing_unknown_references(task):
            self._session.add(_copy_onto(TaskModel(id=task.id), task))

    async def get(self, task_id: uuid.UUID) -> Task | None:
        row = await self._session.get(TaskModel, task_id)
        return None if row is None else _to_task(row)

    async def get_for_update(self, task_id: uuid.UUID) -> Task | None:
        row = await self._session.get(
            TaskModel, task_id, with_for_update=True, populate_existing=True
        )
        return None if row is None else _to_task(row)

    async def get_by_key(self, key: TaskKey) -> Task | None:
        row = await self._session.scalar(select(TaskModel).where(TaskModel.key == str(key)))
        return None if row is None else _to_task(row)

    async def search(self, query: TaskQuery, *, today: date) -> TaskPage:
        """Two statements whatever the page holds: the page, and what matches by status."""
        where = conditions(query.filter, today)
        rows = await self._session.scalars(
            select(TaskModel)
            .where(*where)
            .order_by(*ordering(query.sort, today))
            .limit(query.limit)
            .offset(query.offset)
        )
        items = [_to_task(row) for row in rows]
        counted = (
            await self._session.execute(
                select(TaskModel.status, func.count()).where(*where).group_by(TaskModel.status)
            )
        ).all()
        totals = every_status({TaskStatus(status): count for status, count in counted})
        return TaskPage(items=items, total=sum(totals.values()), status_totals=totals)

    async def count_open(self, *, viewer_id: uuid.UUID, today: date) -> TaskCounts:
        row = (
            await self._session.execute(
                select(
                    func.count(),
                    func.count().filter(TaskModel.assignee_id == viewer_id),
                    func.count().filter(signal_condition(TaskSignal.OVERDUE, today)),
                ).where(IS_OPEN)
            )
        ).one()
        return TaskCounts(all=row[0], mine=row[1], overdue=row[2])

    async def count_signals(self, task_filter: TaskFilter, *, today: date) -> SignalCounts:
        row = (
            await self._session.execute(
                select(
                    *(func.count().filter(signal_condition(s, today)) for s in TaskSignal)
                ).where(*conditions(task_filter, today))
            )
        ).one()
        return SignalCounts(overdue=row[0], p0_at_risk=row[1], due_soon=row[2], needs_owner=row[3])

    async def update(self, task: Task) -> None:
        row = await self._session.get(TaskModel, task.id)
        if row is None:
            raise TaskNotFound(task.id)
        async with self._refusing_unknown_references(task):
            _copy_onto(row, task)

    async def delete(self, task_id: uuid.UUID) -> None:
        row = await self._session.get(TaskModel, task_id)
        if row is None:
            raise TaskNotFound(task_id)
        await self._session.delete(row)
        await self._session.flush()

    @asynccontextmanager
    async def _refusing_unknown_references(self, task: Task) -> AsyncIterator[None]:
        """Write inside a savepoint and let the foreign keys have the last word.

        The use cases ask the ``UserDirectory`` first, but a user can vanish between that
        answer and this write; the key, not the earlier SELECT, is what makes it race-safe.
        The savepoint undoes only this write, so the rest of the unit of work stays usable.
        The same goes for the project. A missing creator is not mapped: ``created_by`` is the
        caller the same transaction has just authenticated, so that violation is a server
        fault, not a bad request.
        """
        try:
            async with self._session.begin_nested():
                yield
        except IntegrityError as error:
            violated = violated_constraint(error)
            if violated == ASSIGNEE_FOREIGN_KEY and task.assignee_id is not None:
                raise InvalidAssigneeError(task.assignee_id) from error
            if violated == PROJECT_FOREIGN_KEY:
                raise UnknownProjectError(task.project_id) from error
            raise


def _copy_onto(row: TaskModel, task: Task) -> TaskModel:
    for field in _FIELDS:
        setattr(row, field, getattr(task, field))
    row.status = task.status.value
    row.priority = task.priority.rank
    return row


def _to_task(row: TaskModel) -> Task:
    try:
        return Task(
            id=row.id,
            status=TaskStatus(row.status),
            priority=TaskPriority.from_rank(row.priority),
            **{field: getattr(row, field) for field in _FIELDS},
        )
    except (InvalidTaskError, ValueError) as error:
        raise StoredTaskInvalid(row.id) from error
