import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.errors import IdentityAlreadyLinkedError
from app.infrastructure.db.constraints import violated_constraint
from app.infrastructure.db.models.user_identity import (
    PROVIDER_SUBJECT_UNIQUE_CONSTRAINT,
    USER_PROVIDER_UNIQUE_CONSTRAINT,
    UserIdentityModel,
)

_UNIQUENESS = {PROVIDER_SUBJECT_UNIQUE_CONSTRAINT, USER_PROVIDER_UNIQUE_CONSTRAINT}


class SqlAlchemyUserIdentityRepository:
    """UserIdentityRepository on PostgreSQL.

    Works inside the session it is given and never commits: the transaction belongs to
    ``transactional_session`` (see ``app.infrastructure.db.unit_of_work``).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_user_id(self, provider: str, subject: str) -> uuid.UUID | None:
        user_id: uuid.UUID | None = await self._session.scalar(
            select(UserIdentityModel.user_id).where(
                UserIdentityModel.provider == provider, UserIdentityModel.subject == subject
            )
        )
        return user_id

    async def link(
        self, user_id: uuid.UUID, provider: str, subject: str, *, linked_at: datetime
    ) -> None:
        try:
            # A savepoint, so a refused link undoes only this insert and the rest of the
            # unit of work stays usable.
            async with self._session.begin_nested():
                self._session.add(
                    UserIdentityModel(
                        id=uuid.uuid4(),
                        user_id=user_id,
                        provider=provider,
                        subject=subject,
                        created_at=linked_at,
                    )
                )
        except IntegrityError as error:
            # The unique constraints, not a prior SELECT, make concurrent sign-ins safe.
            if violated_constraint(error) in _UNIQUENESS:
                raise IdentityAlreadyLinkedError from error
            raise
