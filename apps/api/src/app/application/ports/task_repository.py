import uuid
from collections.abc import Sequence
from typing import Protocol

from app.domain.task import Task


class TaskRepository(Protocol):
    """Stores tasks. Returned tasks are detached: a change is stored only by ``update``.

    A stored task that breaks a domain rule is reported as ``StoredTaskInvalid``.
    """

    async def add(self, task: Task) -> None:
        """Store a new task."""
        ...

    async def get(self, task_id: uuid.UUID) -> Task | None:
        """The task with that id, or ``None``."""
        ...

    async def get_for_update(self, task_id: uuid.UUID) -> Task | None:
        """Like ``get``, and nobody else can change the task until the unit of work ends.

        A second caller waits here and then reads what the first one stored, so a
        read-modify-write built on it never works from a stale task.
        """
        ...

    async def list(self) -> Sequence[Task]:
        """Every task, newest first (``created_at``, then ``id``, descending)."""
        ...

    async def update(self, task: Task) -> None:
        """Store the current state of an existing task. Raises ``TaskNotFound``."""
        ...

    async def delete(self, task_id: uuid.UUID) -> None:
        """Remove the task. Raises ``TaskNotFound``."""
        ...
