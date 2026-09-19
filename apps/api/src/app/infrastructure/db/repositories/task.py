import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.errors import TaskNotFound
from app.domain.task import Task, TaskStatus
from app.infrastructure.db.models.task import TaskModel

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
        self._session.add(_copy_onto(TaskModel(id=task.id), task))
        await self._session.flush()

    async def get(self, task_id: uuid.UUID) -> Task | None:
        row = await self._session.get(TaskModel, task_id)
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
        _copy_onto(row, task)
        await self._session.flush()

    async def delete(self, task_id: uuid.UUID) -> None:
        row = await self._session.get(TaskModel, task_id)
        if row is None:
            raise TaskNotFound(task_id)
        await self._session.delete(row)
        await self._session.flush()


def _copy_onto(row: TaskModel, task: Task) -> TaskModel:
    for field in _FIELDS:
        setattr(row, field, getattr(task, field))
    row.status = task.status.value
    return row


def _to_task(row: TaskModel) -> Task:
    return Task(
        id=row.id,
        status=TaskStatus(row.status),
        **{field: getattr(row, field) for field in _FIELDS},
    )
