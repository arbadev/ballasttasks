"""A task's activity: an append-only timeline of log lines and comments.

Standard library only. An entry is written once and never changed; what a ``log`` entry
says is decided in ``app.domain.activity_log``.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Self

from app.domain.user import initials_of

ACTIVITY_TEXT_MAX_LENGTH = 2000


class InvalidActivityError(ValueError):
    """The text of an entry cannot be stored."""


class ActivityKind(StrEnum):
    LOG = "log"  # written by the application when something happened to the task
    COMMENT = "comment"  # written by a person


@dataclass(frozen=True, slots=True)
class ActivityEntry:
    id: uuid.UUID
    task_id: uuid.UUID
    kind: ActivityKind
    text: str
    actor_id: uuid.UUID
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", _valid_text(self.text))
        if self.created_at.utcoffset() is None:
            raise InvalidActivityError("timestamps must be timezone-aware")

    @classmethod
    def log(
        cls,
        *,
        entry_id: uuid.UUID,
        task_id: uuid.UUID,
        actor_id: uuid.UUID,
        text: str,
        now: datetime,
    ) -> Self:
        return cls(entry_id, task_id, ActivityKind.LOG, text, actor_id, now)

    @classmethod
    def comment(
        cls,
        *,
        entry_id: uuid.UUID,
        task_id: uuid.UUID,
        actor_id: uuid.UUID,
        text: str,
        now: datetime,
    ) -> Self:
        return cls(entry_id, task_id, ActivityKind.COMMENT, text, actor_id, now)


@dataclass(frozen=True, slots=True)
class Actor:
    """Who an entry is by, as anybody may see them: a name, never an email."""

    id: uuid.UUID
    full_name: str

    @property
    def initials(self) -> str:
        return initials_of(self.full_name)


def _valid_text(text: str) -> str:
    if "\x00" in text:
        raise InvalidActivityError("text must not contain the NUL character")
    stripped = text.strip()
    if not stripped:
        raise InvalidActivityError("text must not be blank")
    if len(stripped) > ACTIVITY_TEXT_MAX_LENGTH:
        raise InvalidActivityError(f"text must be at most {ACTIVITY_TEXT_MAX_LENGTH} characters")
    return stripped
