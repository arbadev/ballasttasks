import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.project import PROJECT_COLOR_MAX_LENGTH, PROJECT_NAME_MAX_LENGTH
from app.domain.task_key import KEY_PREFIX_MAX_LENGTH, KEY_PREFIX_MIN_LENGTH
from app.infrastructure.db.base import Base

# Spelled out (it follows Base.metadata's naming convention) because the repository
# recognises a taken key by this name.
KEY_UNIQUE_CONSTRAINT = "uq_projects_key"


class ProjectModel(Base):
    """Persistence shape of a project. The rules live in ``app.domain.project``; the CHECK
    constraints only stop a row no project could be rebuilt from.

    ``next_task_number`` is the counter task keys come from. It is not part of the
    ``Project`` entity: only ``SqlAlchemyProjectRepository.allocate_task_key`` touches it, in
    one ``UPDATE ... RETURNING`` (see ADR 0005).
    """

    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("key", name=KEY_UNIQUE_CONSTRAINT),
        CheckConstraint(
            f"key ~ '^[A-Z]{{{KEY_PREFIX_MIN_LENGTH},{KEY_PREFIX_MAX_LENGTH}}}$'", name="key_shape"
        ),
        CheckConstraint("next_task_number >= 1", name="next_task_number_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(PROJECT_NAME_MAX_LENGTH))
    key: Mapped[str] = mapped_column(String(KEY_PREFIX_MAX_LENGTH))
    color: Mapped[str | None] = mapped_column(String(PROJECT_COLOR_MAX_LENGTH))
    next_task_number: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
