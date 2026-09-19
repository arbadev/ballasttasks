import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.activity import ActivityKind
from app.infrastructure.db.base import Base

_KINDS = ", ".join(f"'{kind.value}'" for kind in ActivityKind)
_IS_COMMENT = f"kind = '{ActivityKind.COMMENT.value}'"


class ActivityModel(Base):
    """Persistence shape of an activity entry: append-only, so there is no ``updated_at``.

    - ``task_id`` is ``ON DELETE CASCADE``: the timeline is part of its task.
    - ``actor_id`` is ``ON DELETE RESTRICT``, like ``tasks.created_by``: an entry never
      silently loses who it is by, so somebody the log names is deactivated, not deleted.
    - ``seq`` is the order of writing. One change can leave several entries at one instant
      (their ``created_at`` is the use case's clock, not the row's), and their ids are
      random; ``seq`` is what orders those, and the feed's index ends with it.

    The partial index serves ``comments_count``: it holds comments only, so counting them
    for a page of tasks never reads the (much longer) log lines.
    """

    __tablename__ = "task_activity"
    __table_args__ = (
        CheckConstraint(f"kind IN ({_KINDS})", name="kind"),
        Index("ix_task_activity_task_id_created_at_seq", "task_id", "created_at", "seq"),
        Index("ix_task_activity_comments_task_id", "task_id", postgresql_where=text(_IS_COMMENT)),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tasks.id", name="fk_task_activity_task_id_tasks", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(10))
    text: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", name="fk_task_activity_actor_id_users", ondelete="RESTRICT"),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
