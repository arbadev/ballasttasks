import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.activity_feed import ActivityItem, ActivityPage
from app.domain.activity import ActivityEntry, ActivityKind, Actor
from app.infrastructure.db.models.activity import ActivityModel
from app.infrastructure.db.models.user import UserModel


class SqlAlchemyActivityLog:
    """ActivityRecorder and ActivityFeed on PostgreSQL, both over ``task_activity``.

    It works inside the session it is given and never commits, which is the whole point of
    recording through it: an entry and the change it describes are one transaction (see
    ``app.infrastructure.db.unit_of_work``). There is no update and no delete.

    The feed joins ``users`` for two columns, so an email or a password hash is never read.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, entry: ActivityEntry) -> None:
        self._session.add(
            ActivityModel(
                id=entry.id,
                task_id=entry.task_id,
                kind=entry.kind.value,
                text=entry.text,
                actor_id=entry.actor_id,
                created_at=entry.created_at,
            )
        )
        # At once, not at commit: ``seq`` is the order of writing, so rows must reach the
        # database in the order they were recorded.
        await self._session.flush()

    async def page(self, task_id: uuid.UUID, *, limit: int, offset: int) -> ActivityPage:
        """Two statements whatever the page holds: the page, and the count of all entries."""
        rows = await self._session.execute(
            select(ActivityModel, UserModel.full_name)
            .join(UserModel, UserModel.id == ActivityModel.actor_id)
            .where(ActivityModel.task_id == task_id)
            .order_by(ActivityModel.created_at.desc(), ActivityModel.seq.desc())
            .limit(limit)
            .offset(offset)
        )
        items = [
            ActivityItem(_to_entry(row), Actor(id=row.actor_id, full_name=full_name))
            for row, full_name in rows
        ]
        total = await self._session.scalar(
            select(func.count()).select_from(ActivityModel).where(ActivityModel.task_id == task_id)
        )
        return ActivityPage(items=items, total=total or 0)


def _to_entry(row: ActivityModel) -> ActivityEntry:
    return ActivityEntry(
        id=row.id,
        task_id=row.task_id,
        kind=ActivityKind(row.kind),
        text=row.text,
        actor_id=row.actor_id,
        created_at=row.created_at,
    )
