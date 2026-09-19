import uuid
from collections.abc import Sequence

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.user import Person
from app.infrastructure.db.models.user import UserModel


class SqlAlchemyUserDirectory:
    """UserDirectory and PeopleDirectory on PostgreSQL, both over the users table.

    ``is_active_user`` is one ``SELECT EXISTS``; ``list_active`` selects three columns, so
    an email or a password hash is never even read.

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

    async def list_active(self) -> Sequence[Person]:
        rows = await self._session.execute(
            select(UserModel.id, UserModel.full_name, UserModel.role_label)
            .where(UserModel.is_active)
            # COLLATE "C": by code point, whatever locale the database was created with.
            .order_by(func.lower(UserModel.full_name).collate("C"), UserModel.id)
        )
        return [
            Person(id=row.id, full_name=row.full_name, role_label=row.role_label) for row in rows
        ]
