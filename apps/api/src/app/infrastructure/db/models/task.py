import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.task import TITLE_MAX_LENGTH, TaskStatus
from app.infrastructure.db.base import Base

# Spelled out (they follow Base.metadata's naming convention) because the repository
# recognises a refused assignee by this name.
CREATOR_FOREIGN_KEY = "fk_tasks_created_by_users"
ASSIGNEE_FOREIGN_KEY = "fk_tasks_assignee_id_users"

_STATUS_VALUES = ", ".join(f"'{status.value}'" for status in TaskStatus)


class TaskModel(Base):
    """Persistence shape of a task. The rules live in ``app.domain.task``, not here; the
    CHECK constraints only stop a row no task could be rebuilt from.

    Both user columns reference ``users.id``, each with a deliberate ``ON DELETE``:

    - ``created_by`` is ``RESTRICT``: a task never silently loses its creator, so a user who
      created tasks cannot be deleted (deactivate them instead).
    - ``assignee_id`` is ``SET NULL``: when an assignee goes away the task stays, unassigned.

    Both are indexed, because those rules make every user delete search this table. The
    repository maps a violation of ``ASSIGNEE_FOREIGN_KEY`` to ``InvalidAssigneeError``.
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
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", name=CREATOR_FOREIGN_KEY, ondelete="RESTRICT"), index=True
    )
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", name=ASSIGNEE_FOREIGN_KEY, ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
