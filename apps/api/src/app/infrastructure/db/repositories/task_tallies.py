import uuid
from collections.abc import Mapping, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.task_tallies import TaskTally
from app.domain.activity import ActivityKind
from app.infrastructure.db.models.activity import ActivityModel
from app.infrastructure.db.models.attachment import AttachmentModel
from app.infrastructure.db.models.step import StepModel


class SqlAlchemyTaskTallies:
    """TaskTallies on PostgreSQL: one statement for a whole page of tasks.

    Steps, comments and attachments are grouped separately, then FULL OUTER JOINed,
    so their counts never multiply. Each group is limited to this page's task IDs;
    comments use the partial comment index. Tasks with only attachments are retained.
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
        attachments = (
            select(
                AttachmentModel.task_id.label("task_id"), func.count().label("attachments_count")
            )
            .where(AttachmentModel.task_id.in_(task_ids))
            .group_by(AttachmentModel.task_id)
            .subquery("attached")
        )
        groups = steps.join(comments, steps.c.task_id == comments.c.task_id, full=True).join(
            attachments,
            func.coalesce(steps.c.task_id, comments.c.task_id) == attachments.c.task_id,
            full=True,
        )
        rows = await self._session.execute(
            select(
                func.coalesce(steps.c.task_id, comments.c.task_id, attachments.c.task_id),
                func.coalesce(steps.c.steps_total, 0),
                func.coalesce(steps.c.steps_done, 0),
                func.coalesce(comments.c.comments_count, 0),
                func.coalesce(attachments.c.attachments_count, 0),
            ).select_from(groups)
        )
        counted = {
            task_id: TaskTally(
                steps_total=total,
                steps_done=done,
                comments_count=comment_count,
                attachments_count=attachment_count,
            )
            for task_id, total, done, comment_count, attachment_count in rows
        }
        return {task_id: counted.get(task_id, TaskTally()) for task_id in task_ids}
