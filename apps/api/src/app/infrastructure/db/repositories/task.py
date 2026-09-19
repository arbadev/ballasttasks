import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.errors import InvalidAssigneeError, StoredTaskInvalid, TaskNotFound
from app.domain.task import InvalidTaskError, Task, TaskStatus
from app.infrastructure.db.constraints import violated_constraint
from app.infrastructure.db.models.task import ASSIGNEE_FOREIGN_KEY, TaskModel

_FIELDS = (
    "title",
    "description",
    "due_date",
    "created_by",
    "assignee_id",
    "created_at",
    "updated_at",
    "completed_at",
)


class SqlAlchemyTaskRepository:
    """TaskRepository on PostgreSQL.

    Works inside the session it is given and never commits: the transaction belongs to
    ``transactional_session`` (see ``app.infrastructure.db.unit_of_work``).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, task: Task) -> None:
        async with self._refusing_an_unknown_assignee(task):
            self._session.add(_copy_onto(TaskModel(id=task.id), task))

    async def get(self, task_id: uuid.UUID) -> Task | None:
        row = await self._session.get(TaskModel, task_id)
        return None if row is None else _to_task(row)

    async def get_for_update(self, task_id: uuid.UUID) -> Task | None:
        row = await self._session.get(
            TaskModel, task_id, with_for_update=True, populate_existing=True
        )
        return None if row is None else _to_task(row)

    async def list(self) -> Sequence[Task]:
        rows = await self._session.scalars(
            select(TaskModel).order_by(TaskModel.created_at.desc(), TaskModel.id.desc())
        )
        return [_to_task(row) for row in rows]

    async def update(self, task: Task) -> None:
        row = await self._session.get(TaskModel, task.id)
        if row is None:
            raise TaskNotFound(task.id)
        async with self._refusing_an_unknown_assignee(task):
            _copy_onto(row, task)

    async def delete(self, task_id: uuid.UUID) -> None:
        row = await self._session.get(TaskModel, task_id)
        if row is None:
            raise TaskNotFound(task_id)
        await self._session.delete(row)
        await self._session.flush()

    @asynccontextmanager
    async def _refusing_an_unknown_assignee(self, task: Task) -> AsyncIterator[None]:
        """Write inside a savepoint and let the assignee foreign key have the last word.

        The use cases ask the ``UserDirectory`` first, but a user can vanish between that
        answer and this write; the key, not the earlier SELECT, is what makes it race-safe.
        The savepoint undoes only this write, so the rest of the unit of work stays usable.
        A missing creator is not mapped: ``created_by`` is the caller the same transaction
        has just authenticated, so that violation is a server fault, not a bad request.
        """
        try:
            async with self._session.begin_nested():
                yield
        except IntegrityError as error:
            if violated_constraint(error) == ASSIGNEE_FOREIGN_KEY and task.assignee_id is not None:
                raise InvalidAssigneeError(task.assignee_id) from error
            raise


def _copy_onto(row: TaskModel, task: Task) -> TaskModel:
    for field in _FIELDS:
        setattr(row, field, getattr(task, field))
    row.status = task.status.value
    return row


def _to_task(row: TaskModel) -> Task:
    try:
        return Task(
            id=row.id,
            status=TaskStatus(row.status),
            **{field: getattr(row, field) for field in _FIELDS},
        )
    except InvalidTaskError as error:
        raise StoredTaskInvalid(row.id) from error
