"""Hand-written test doubles for the application ports."""

import asyncio
import uuid
from collections.abc import Sequence
from dataclasses import replace

from app.application.errors import InvalidAssigneeError, TaskNotFound
from app.domain.task import Task
from tests.auth_fakes import InMemoryUserRepository


class StubHealthCheck:
    def __init__(self, name: str, *, healthy: bool = True) -> None:
        self.name = name
        self._healthy = healthy

    async def check(self) -> bool:
        return self._healthy


class RaisingHealthCheck:
    def __init__(self, name: str) -> None:
        self.name = name

    async def check(self) -> bool:
        raise RuntimeError(f"{self.name} exploded")


class HangingHealthCheck:
    def __init__(self, name: str) -> None:
        self.name = name

    async def check(self) -> bool:
        await asyncio.sleep(60)
        return True


class InMemoryTaskRepository:
    """TaskRepository fake; passes the same contract suite as the PostgreSQL adapter.

    Tasks are copied on the way in and out, as a database would, so a change is only
    stored by an explicit ``update``. It reads the users fake the way the ``tasks`` table
    references ``users``: an assignee who is not stored there is refused.
    """

    def __init__(self, users: InMemoryUserRepository) -> None:
        self._users = users
        self._tasks: dict[uuid.UUID, Task] = {}

    async def _refuse_an_unknown_assignee(self, task: Task) -> None:
        if task.assignee_id is not None and await self._users.get_by_id(task.assignee_id) is None:
            raise InvalidAssigneeError(task.assignee_id)

    async def add(self, task: Task) -> None:
        await self._refuse_an_unknown_assignee(task)
        self._tasks[task.id] = replace(task)

    async def get(self, task_id: uuid.UUID) -> Task | None:
        task = self._tasks.get(task_id)
        return None if task is None else replace(task)

    async def get_for_update(self, task_id: uuid.UUID) -> Task | None:
        # No transactions here, so there is never a second writer to wait for.
        return await self.get(task_id)

    async def list(self) -> Sequence[Task]:
        newest_first = sorted(
            self._tasks.values(), key=lambda task: (task.created_at, task.id), reverse=True
        )
        return [replace(task) for task in newest_first]

    async def update(self, task: Task) -> None:
        if task.id not in self._tasks:
            raise TaskNotFound(task.id)
        await self._refuse_an_unknown_assignee(task)
        self._tasks[task.id] = replace(task)

    async def delete(self, task_id: uuid.UUID) -> None:
        if task_id not in self._tasks:
            raise TaskNotFound(task_id)
        del self._tasks[task_id]
