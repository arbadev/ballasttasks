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

from app.domain.task_key import InvalidTaskKeyError, TaskKey

TITLE_MAX_LENGTH = 200
DESCRIPTION_MAX_LENGTH = 5000
IMPORTANCE_MIN = 0
IMPORTANCE_MAX = 100


class InvalidTaskError(ValueError):
    """A task would break one of its invariants."""


class TaskStatus(StrEnum):
    """The design's four columns. Everything except ``done`` is open."""

    TODO = "todo"
    IN_PROGRESS = "in_progress"
    TESTING = "testing"
    DONE = "done"


class TaskPriority(StrEnum):
    """``P0`` is the most urgent. ``rank`` is the number the design computes with."""

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"

    @property
    def rank(self) -> int:
        return int(self.value[1])

    @classmethod
    def from_rank(cls, rank: int) -> Self:
        return cls(f"P{rank}")


# What the design's ``create`` gives a new task (``prio: 2, importance: 50``).
DEFAULT_PRIORITY = TaskPriority.P2
DEFAULT_IMPORTANCE = 50


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
    project_id: uuid.UUID
    # ``<PREFIX>-<NN>`` in canonical form. It never changes, not even when the task moves to
    # another project: it is what people have already written down.
    key: str
    priority: TaskPriority
    importance: int

    def __post_init__(self) -> None:
        self.title = _valid_title(self.title)
        _check_description(self.description)
        _check_key(self.key)
        _check_importance(self.importance)
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
        project_id: uuid.UUID,
        key: TaskKey | str,
        now: datetime,
        description: str | None = None,
        status: TaskStatus = TaskStatus.TODO,
        due_date: date | None = None,
        assignee_id: uuid.UUID | None = None,
        priority: TaskPriority = DEFAULT_PRIORITY,
        importance: int = DEFAULT_IMPORTANCE,
    ) -> Self:
        """A new task, created and updated ``now``: ``todo`` unless the caller names the
        column it was added to, and completed ``now`` when that column is ``done``."""
        return cls(
            id=task_id,
            title=title,
            description=description,
            status=status,
            due_date=due_date,
            created_by=created_by,
            assignee_id=assignee_id,
            created_at=now,
            updated_at=now,
            completed_at=now if status is TaskStatus.DONE else None,
            project_id=project_id,
            key=str(key),
            priority=priority,
            importance=importance,
        )

    @property
    def is_open(self) -> bool:
        return self.status is not TaskStatus.DONE

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

    def prioritise(self, priority: TaskPriority, *, now: datetime) -> None:
        self._touch(now)
        self.priority = priority

    def weigh(self, importance: int, *, now: datetime) -> None:
        _check_importance(importance)
        self._touch(now)
        self.importance = importance

    def move_to_project(self, project_id: uuid.UUID, *, now: datetime) -> None:
        """The key stays: it names where the task was created, not where it lives now."""
        self._touch(now)
        self.project_id = project_id

    def move_to(self, status: TaskStatus, *, now: datetime) -> None:
        """Entering ``done`` records ``completed_at``; leaving ``done`` clears it."""
        self._touch(now)
        if status is not TaskStatus.DONE:
            self.completed_at = None
        elif self.status is not TaskStatus.DONE:
            self.completed_at = now
        self.status = status

    def touch(self, *, now: datetime) -> None:
        """Something that belongs to the task changed (an attachment came or went): the task
        itself is as it was, but it has been worked on."""
        self._touch(now)

    def _touch(self, now: datetime) -> None:
        _check_aware(now)
        self.updated_at = now


def _valid_title(title: str) -> str:
    _check_no_nul("title", title)
    stripped = title.strip()
    if not stripped:
        raise InvalidTaskError("title must not be blank")
    if len(stripped) > TITLE_MAX_LENGTH:
        raise InvalidTaskError(f"title must be at most {TITLE_MAX_LENGTH} characters")
    return stripped


def _check_description(description: str | None) -> None:
    if description is None:
        return
    _check_no_nul("description", description)
    if len(description) > DESCRIPTION_MAX_LENGTH:
        raise InvalidTaskError(f"description must be at most {DESCRIPTION_MAX_LENGTH} characters")


def _check_key(key: str) -> None:
    try:
        canonical = str(TaskKey.parse(key))
    except InvalidTaskKeyError as error:
        raise InvalidTaskError(f"key: {error}") from error
    if canonical != key:
        raise InvalidTaskError(f"key must be in canonical form ({canonical})")


def _check_importance(importance: int) -> None:
    # ``bool`` is an ``int`` in Python; ``True`` is not an importance.
    if type(importance) is not int or not IMPORTANCE_MIN <= importance <= IMPORTANCE_MAX:
        raise InvalidTaskError(
            f"importance must be a whole number from {IMPORTANCE_MIN} to {IMPORTANCE_MAX}"
        )


def _check_no_nul(field: str, text: str) -> None:
    if "\x00" in text:
        raise InvalidTaskError(f"{field} must not contain the NUL character")


def _check_aware(moment: datetime | None) -> None:
    if moment is not None and moment.utcoffset() is None:
        raise InvalidTaskError("timestamps must be timezone-aware")
