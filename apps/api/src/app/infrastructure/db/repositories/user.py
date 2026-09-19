import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.errors import EmailAlreadyRegisteredError
from app.domain.user import User
from app.infrastructure.db.constraints import violated_constraint
from app.infrastructure.db.models.user import EMAIL_UNIQUE_CONSTRAINT, UserModel


class SqlAlchemyUserRepository:
    """UserRepository on PostgreSQL.

    Works inside the session it is given and never commits: the transaction belongs to
    ``transactional_session`` (see ``app.infrastructure.db.unit_of_work``).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user: User) -> None:
        try:
            # A savepoint, so a rejected email undoes only this insert and the rest of the
            # unit of work stays usable.
            async with self._session.begin_nested():
                self._session.add(_to_model(user))
        except IntegrityError as error:
            # The unique constraint, not a prior SELECT, is what makes registration race-safe.
            if violated_constraint(error) == EMAIL_UNIQUE_CONSTRAINT:
                raise EmailAlreadyRegisteredError(user.email) from error
            raise

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        model = await self._session.get(UserModel, user_id)
        return None if model is None else _to_entity(model)

    async def get_by_email(self, email: str) -> User | None:
        model = await self._session.scalar(select(UserModel).where(UserModel.email == email))
        return None if model is None else _to_entity(model)


def _to_model(user: User) -> UserModel:
    return UserModel(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        hashed_password=user.hashed_password,
        is_active=user.is_active,
        created_at=user.created_at,
    )


def _to_entity(model: UserModel) -> User:
    return User(
        id=model.id,
        email=model.email,
        full_name=model.full_name,
        hashed_password=model.hashed_password,
        is_active=model.is_active,
        created_at=model.created_at,
    )
