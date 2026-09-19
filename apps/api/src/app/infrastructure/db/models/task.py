import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.task import TITLE_MAX_LENGTH, TaskStatus
from app.infrastructure.db.base import Base

_STATUS_VALUES = ", ".join(f"'{status.value}'" for status in TaskStatus)


class TaskModel(Base):
    """Persistence shape of a task. The rules live in ``app.domain.task``, not here; the
    CHECK constraints only stop a row no task could be rebuilt from.

    ``created_by`` and ``assignee_id`` are plain UUIDs for now: the foreign keys from
    ``tasks.created_by`` and ``tasks.assignee_id`` to ``users.id``, and the check that an
    assignee exists, arrive in the follow-up change that wires tasks to users.
    """

    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(f"status IN ({_STATUS_VALUES})", name="status"),
        CheckConstraint(
            f"(status = '{TaskStatus.DONE.value}') = (completed_at IS NOT NULL)",
            name="completed_at_follows_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    title: Mapped[str] = mapped_column(String(TITLE_MAX_LENGTH))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), index=True)
    due_date: Mapped[date | None] = mapped_column(Date, index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
