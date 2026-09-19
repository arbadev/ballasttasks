import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.errors import StepNotFound
from app.domain.step import Step
from app.infrastructure.db.models.step import StepModel


class SqlAlchemyStepRepository:
    """StepRepository on PostgreSQL.

    Works inside the session it is given and never commits (see
    ``app.infrastructure.db.unit_of_work``). Every write is flushed at once, so the rows a
    use case reads next are the ones it has just written.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, step: Step) -> None:
        self._session.add(
            StepModel(
                id=step.id,
                task_id=step.task_id,
                title=step.title,
                done=step.done,
                position=step.position,
                created_at=step.created_at,
            )
        )
        await self._session.flush()

    async def list_for_task(self, task_id: uuid.UUID) -> Sequence[Step]:
        rows = await self._session.scalars(
            select(StepModel).where(StepModel.task_id == task_id).order_by(StepModel.position)
        )
        return [_to_step(row) for row in rows]

    async def update(self, step: Step) -> None:
        row = await self._session.get(StepModel, step.id)
        if row is None:
            raise StepNotFound(step.id)
        row.title, row.done, row.position = step.title, step.done, step.position
        await self._session.flush()

    async def delete(self, step_id: uuid.UUID) -> None:
        row = await self._session.get(StepModel, step_id)
        if row is None:
            raise StepNotFound(step_id)
        await self._session.delete(row)
        await self._session.flush()


def _to_step(row: StepModel) -> Step:
    return Step(
        id=row.id,
        task_id=row.task_id,
        title=row.title,
        done=row.done,
        position=row.position,
        created_at=row.created_at,
    )
