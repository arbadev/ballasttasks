import uuid
from datetime import date
from typing import Protocol

from app.application.task_query import SignalCounts, TaskCounts, TaskFilter, TaskPage, TaskQuery
from app.domain.task import Task
from app.domain.task_key import TaskKey


class TaskRepository(Protocol):
    """Stores tasks. Returned tasks are detached: a change is stored only by ``update``.

    A stored task that breaks a domain rule is reported as ``StoredTaskInvalid``.

    Tasks reference users and a project: ``add`` and ``update`` raise
    ``InvalidAssigneeError`` when the assignee is not a stored user and ``UnknownProjectError``
    when the project is not stored, store nothing, and stay usable. Whether that user is
    still active is not the store's question; the use cases ask a ``UserDirectory``.

    The store has no clock: every question that depends on the date takes ``today``.
    """

    async def add(self, task: Task) -> None:
        """Store a new task. Raises ``InvalidAssigneeError``, ``UnknownProjectError``."""
        ...

    async def get(self, task_id: uuid.UUID) -> Task | None:
        """The task with that id, or ``None``."""
        ...

    async def get_by_key(self, key: TaskKey) -> Task | None:
        """The task with that key, or ``None``. A key stays with its task for good."""
        ...

    async def get_for_update(self, task_id: uuid.UUID) -> Task | None:
        """Like ``get``, and nobody else can change the task until the unit of work ends.

        A second caller waits here and then reads what the first one stored, so a
        read-modify-write built on it never works from a stale task.
        """
        ...

    async def search(self, query: TaskQuery, *, today: date) -> TaskPage:
        """One page of the tasks the filter selects, in the order asked for, and how many
        tasks the filter selects in all. See ``app.application.task_query``."""
        ...

    async def count_open(self, *, viewer_id: uuid.UUID, today: date) -> TaskCounts:
        """The open tasks of the whole workspace: all, the viewer's, the overdue ones."""
        ...

    async def count_signals(self, task_filter: TaskFilter, *, today: date) -> SignalCounts:
        """How many of the tasks the filter selects raise each Attention signal."""
        ...

    async def update(self, task: Task) -> None:
        """Store the current state of an existing task.

        Raises ``TaskNotFound``, ``InvalidAssigneeError`` or ``UnknownProjectError``.
        """
        ...

    async def delete(self, task_id: uuid.UUID) -> None:
        """Remove the task. Raises ``TaskNotFound``."""
        ...
