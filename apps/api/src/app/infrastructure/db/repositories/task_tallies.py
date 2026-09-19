import uuid
from collections.abc import Mapping, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.task_tallies import TaskTally
from app.domain.activity import ActivityKind
from app.infrastructure.db.models.activity import ActivityModel
from app.infrastructure.db.models.step import StepModel


class SqlAlchemyTaskTallies:
    """TaskTallies on PostgreSQL: one statement for a whole page of tasks.

    Steps and comments are each grouped by task on their own and then put side by side
    (``FULL OUTER JOIN``), so neither count multiplies the other, which a single join of
    ``tasks``, ``task_steps`` and ``task_activity`` would do. Both sides are index-only
    lookups by ``task_id``; the comments side reads the partial index of comments.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def for_tasks(self, task_ids: Sequence[uuid.UUID]) -> Mapping[uuid.UUID, TaskTally]:
        if not task_ids:
            return {}
        steps = (
            select(
                StepModel.task_id.label("task_id"),
                func.count().label("steps_total"),
                func.count().filter(StepModel.done).label("steps_done"),
            )
            .where(StepModel.task_id.in_(task_ids))
            .group_by(StepModel.task_id)
            .subquery("steps")
        )
        comments = (
            select(ActivityModel.task_id.label("task_id"), func.count().label("comments_count"))
            .where(
                ActivityModel.task_id.in_(task_ids),
                ActivityModel.kind == ActivityKind.COMMENT.value,
            )
            .group_by(ActivityModel.task_id)
            .subquery("comments")
        )
        rows = await self._session.execute(
            select(
                func.coalesce(steps.c.task_id, comments.c.task_id),
                func.coalesce(steps.c.steps_total, 0),
                func.coalesce(steps.c.steps_done, 0),
                func.coalesce(comments.c.comments_count, 0),
            ).select_from(steps.join(comments, steps.c.task_id == comments.c.task_id, full=True))
        )
        counted = {
            task_id: TaskTally(steps_total=total, steps_done=done, comments_count=comment_count)
            for task_id, total, done, comment_count in rows
        }
        return {task_id: counted.get(task_id, TaskTally()) for task_id in task_ids}
