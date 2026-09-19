import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.step import STEP_TITLE_MAX_LENGTH
from app.infrastructure.db.base import Base


class StepModel(Base):
    """Persistence shape of a step. The rules live in ``app.domain.step``.

    ``task_id`` is ``ON DELETE CASCADE``: a step is part of its task and goes with it.

    Positions are unique per task, and the constraint is ``DEFERRABLE INITIALLY DEFERRED``:
    it is checked when the unit of work ends, because a reorder passes through states in
    which two steps share a position. It is the backstop, not the mechanism: the step use
    cases hold the task row while they renumber (ADR 0007). Its index also serves the one
    read there is, "the steps of this task, by position".
    """

    __tablename__ = "task_steps"
    __table_args__ = (
        CheckConstraint("position >= 0", name="position"),
        UniqueConstraint(
            "task_id",
            "position",
            name="uq_task_steps_task_id_position",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tasks.id", name="fk_task_steps_task_id_tasks", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(STEP_TITLE_MAX_LENGTH))
    done: Mapped[bool] = mapped_column(Boolean)
    position: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
