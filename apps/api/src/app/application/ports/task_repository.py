import uuid
from collections.abc import Sequence
from typing import Protocol

from app.domain.task import Task


class TaskRepository(Protocol):
    """Stores tasks. Returned tasks are detached: a change is stored only by ``update``."""

    async def add(self, task: Task) -> None:
        """Store a new task."""
        ...

    async def get(self, task_id: uuid.UUID) -> Task | None:
        """The task with that id, or ``None``."""
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
