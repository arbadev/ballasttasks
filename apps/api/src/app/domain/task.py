"""The Task entity and the rules that hold wherever a task exists.

Standard library only. State changes go through the methods below so the invariants
(title rules, ``completed_at`` follows ``status``) cannot be skipped; ``__post_init__``
applies the same rules when a stored task is rebuilt.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Self

TITLE_MAX_LENGTH = 200
DESCRIPTION_MAX_LENGTH = 5000


class InvalidTaskError(ValueError):
    """A task would break one of its invariants."""


class TaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"


@dataclass(slots=True)
class Task:
    id: uuid.UUID
    title: str
    description: str | None
    status: TaskStatus
    due_date: date | None
    created_by: uuid.UUID
    assignee_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None

    def __post_init__(self) -> None:
        self.title = _valid_title(self.title)
        _check_description(self.description)
        for moment in (self.created_at, self.updated_at, self.completed_at):
            _check_aware(moment)
        if (self.status is TaskStatus.DONE) != (self.completed_at is not None):
            raise InvalidTaskError("completed_at must be set exactly when the status is done")

    @classmethod
    def create(
        cls,
        *,
        task_id: uuid.UUID,
        title: str,
        created_by: uuid.UUID,
        now: datetime,
        description: str | None = None,
        due_date: date | None = None,
        assignee_id: uuid.UUID | None = None,
    ) -> Self:
        """A new task: ``todo``, not completed, created and updated ``now``."""
        return cls(
            id=task_id,
            title=title,
            description=description,
            status=TaskStatus.TODO,
            due_date=due_date,
            created_by=created_by,
            assignee_id=assignee_id,
            created_at=now,
            updated_at=now,
            completed_at=None,
        )

    def retitle(self, title: str, *, now: datetime) -> None:
        valid_title = _valid_title(title)
        self._touch(now)
        self.title = valid_title

    def describe(self, description: str | None, *, now: datetime) -> None:
        _check_description(description)
        self._touch(now)
        self.description = description

    def reschedule(self, due_date: date | None, *, now: datetime) -> None:
        self._touch(now)
        self.due_date = due_date

    def assign_to(self, assignee_id: uuid.UUID | None, *, now: datetime) -> None:
        self._touch(now)
        self.assignee_id = assignee_id

    def move_to(self, status: TaskStatus, *, now: datetime) -> None:
        """Entering ``done`` records ``completed_at``; leaving ``done`` clears it."""
        self._touch(now)
        if status is not TaskStatus.DONE:
            self.completed_at = None
        elif self.status is not TaskStatus.DONE:
            self.completed_at = now
        self.status = status

    def _touch(self, now: datetime) -> None:
        _check_aware(now)
        self.updated_at = now


def _valid_title(title: str) -> str:
    stripped = title.strip()
    if not stripped:
        raise InvalidTaskError("title must not be blank")
    if len(stripped) > TITLE_MAX_LENGTH:
        raise InvalidTaskError(f"title must be at most {TITLE_MAX_LENGTH} characters")
    return stripped


def _check_description(description: str | None) -> None:
    if description is not None and len(description) > DESCRIPTION_MAX_LENGTH:
        raise InvalidTaskError(f"description must be at most {DESCRIPTION_MAX_LENGTH} characters")


def _check_aware(moment: datetime | None) -> None:
    if moment is not None and moment.utcoffset() is None:
        raise InvalidTaskError("timestamps must be timezone-aware")
