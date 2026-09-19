import uuid
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Final

from app.application.clock import Clock, utc_now
from app.application.errors import TaskNotFound
from app.application.ports.task_repository import TaskRepository
from app.domain.task import Task, TaskStatus


class Unset(Enum):
    """Marks a field the caller did not mention; ``None`` means "clear it"."""

    UNSET = "unset"


UNSET: Final = Unset.UNSET


@dataclass(frozen=True, slots=True)
class TaskChanges:
    """A partial update: only the fields that are set are applied."""

    title: str | Unset = UNSET
    description: str | Unset | None = UNSET
    status: TaskStatus | Unset = UNSET
    due_date: date | Unset | None = UNSET
    assignee_id: uuid.UUID | Unset | None = UNSET


class UpdateTask:
    """Completing a task is ``status=done``; assigning it is ``assignee_id=<user id>``."""

    def __init__(self, tasks: TaskRepository, *, clock: Clock = utc_now) -> None:
        self._tasks = tasks
        self._clock = clock

    async def execute(self, task_id: uuid.UUID, changes: TaskChanges) -> Task:
        """Raises ``TaskNotFound``, or ``InvalidTaskError`` before anything is stored."""
        task = await self._tasks.get(task_id)
        if task is None:
            raise TaskNotFound(task_id)
        if changes == TaskChanges():
            return task

        now = self._clock()
        if changes.title is not UNSET:
            task.retitle(changes.title, now=now)
        if changes.description is not UNSET:
            task.describe(changes.description, now=now)
        if changes.status is not UNSET:
            task.move_to(changes.status, now=now)
        if changes.due_date is not UNSET:
            task.reschedule(changes.due_date, now=now)
        if changes.assignee_id is not UNSET:
            task.assign_to(changes.assignee_id, now=now)

        await self._tasks.update(task)
        return task
