import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.attachment import NAME_MAX_LENGTH, URL_MAX_LENGTH, AttachmentKind
from app.infrastructure.db.base import Base

# Spelled out (it follows Base.metadata's naming convention) because the repository
# recognises an attachment of a task that is not stored by this name.
TASK_FOREIGN_KEY = "fk_attachments_task_id_tasks"

STORAGE_KEY_MAX_LENGTH = 200
CONTENT_TYPE_MAX_LENGTH = 100

_KIND_VALUES = ", ".join(f"'{kind.value}'" for kind in AttachmentKind)
_LINK = f"kind = '{AttachmentKind.LINK.value}'"
_NO_FILE = "storage_key IS NULL AND content_type IS NULL AND size_bytes IS NULL"
_A_FILE = "storage_key IS NOT NULL AND content_type IS NOT NULL AND size_bytes IS NOT NULL"


class AttachmentModel(Base):
    """Persistence shape of an attachment. The rules live in ``app.domain.attachment``; the
    CHECK constraints only stop a row no attachment could be rebuilt from.

    - ``task_id`` is ``CASCADE``: an attachment is part of its task and goes with it. The
      stored file is not a row, so whoever deletes a task removes the files (``DeleteTask``).
    - ``created_by`` is ``RESTRICT``, like ``tasks.created_by``: a user who attached something
      cannot be deleted, only deactivated.
    - ``storage_key`` is unique: two attachments never share a stored file, so removing one
      can never take away another one's content.
    """

    __tablename__ = "attachments"
    __table_args__ = (
        CheckConstraint(f"kind IN ({_KIND_VALUES})", name="kind"),
        CheckConstraint(
            f"({_LINK} AND url IS NOT NULL AND {_NO_FILE}) "
            f"OR (NOT {_LINK} AND url IS NULL AND {_A_FILE})",
            name="fields_follow_kind",
        ),
        CheckConstraint("size_bytes > 0", name="size_bytes_positive"),
        UniqueConstraint("storage_key", name="uq_attachments_storage_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tasks.id", name=TASK_FOREIGN_KEY, ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH))
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    url: Mapped[str | None] = mapped_column(String(URL_MAX_LENGTH))
    storage_key: Mapped[str | None] = mapped_column(String(STORAGE_KEY_MAX_LENGTH))
    content_type: Mapped[str | None] = mapped_column(String(CONTENT_TYPE_MAX_LENGTH))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
