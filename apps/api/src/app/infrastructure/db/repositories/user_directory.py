import uuid

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models.user import UserModel


class SqlAlchemyUserDirectory:
    """UserDirectory on PostgreSQL: one ``SELECT EXISTS`` over the users table.

    It reads in the session it is given, so the answer belongs to the same transaction as
    the task that is about to be written. It loads no row: no email and no password hash
    ever reach the task use cases.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def is_active_user(self, user_id: uuid.UUID) -> bool:
        found = await self._session.scalar(
            select(exists().where(UserModel.id == user_id, UserModel.is_active))
        )
        return bool(found)
