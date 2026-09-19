import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.user import FULL_NAME_MAX_LENGTH, MAX_EMAIL_LENGTH, ROLE_LABEL_MAX_LENGTH
from app.infrastructure.db.base import Base

EMAIL_UNIQUE_CONSTRAINT = "uq_users_email"


class UserModel(Base):
    """Persistence shape of a user. Emails arrive normalised, so plain uniqueness is enough."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name=EMAIL_UNIQUE_CONSTRAINT),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(MAX_EMAIL_LENGTH))
    full_name: Mapped[str] = mapped_column(String(FULL_NAME_MAX_LENGTH))
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    role_label: Mapped[str | None] = mapped_column(String(ROLE_LABEL_MAX_LENGTH))
