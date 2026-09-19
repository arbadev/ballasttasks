import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base

PROVIDER_SUBJECT_UNIQUE_CONSTRAINT = "uq_user_identities_provider_subject"
USER_PROVIDER_UNIQUE_CONSTRAINT = "uq_user_identities_user_id_provider"


class UserIdentityModel(Base):
    """A user's identity at an external provider.

    ``(provider, subject)`` names one person, so it belongs to one user; and a user has at
    most one identity per provider, so a mailbox that changes hands at the provider cannot
    be attached to the account of whoever held it before.
    """

    __tablename__ = "user_identities"
    __table_args__ = (
        UniqueConstraint("provider", "subject", name=PROVIDER_SUBJECT_UNIQUE_CONSTRAINT),
        UniqueConstraint("user_id", "provider", name=USER_PROVIDER_UNIQUE_CONSTRAINT),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    # CASCADE: an identity means nothing without its user. (user_id, provider) is the
    # leading part of a unique index, which also serves the cascade's lookup.
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(50))
    subject: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
