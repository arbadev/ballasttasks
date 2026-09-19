import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.errors import EmailAlreadyRegisteredError
from app.domain.user import User
from app.infrastructure.db.models.user import EMAIL_UNIQUE_CONSTRAINT, UserModel


class SqlAlchemyUserRepository:
    """PostgreSQL ``UserRepository``. Each call is its own short transaction."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def add(self, user: User) -> None:
        try:
            async with self._session_factory() as session, session.begin():
                session.add(_to_model(user))
        except IntegrityError as error:
            # The unique constraint, not a prior SELECT, is what makes registration race-safe.
            if _violated_constraint(error) == EMAIL_UNIQUE_CONSTRAINT:
                raise EmailAlreadyRegisteredError(user.email) from error
            raise

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        async with self._session_factory() as session:
            model = await session.get(UserModel, user_id)
        return _to_entity(model) if model is not None else None

    async def get_by_email(self, email: str) -> User | None:
        async with self._session_factory() as session:
            model = await session.scalar(select(UserModel).where(UserModel.email == email))
        return _to_entity(model) if model is not None else None


def _violated_constraint(error: IntegrityError) -> str | None:
    diagnostics = getattr(error.orig, "diag", None)
    name = getattr(diagnostics, "constraint_name", None)
    return name if isinstance(name, str) else None


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
