"""Hand-written test doubles for the application ports."""

import asyncio
import uuid
from collections.abc import Sequence
from dataclasses import replace

from app.application.errors import TaskNotFound

from app.domain.task import Task


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
    stored by an explicit ``update``.
    """

    def __init__(self) -> None:
        self._tasks: dict[uuid.UUID, Task] = {}

    async def add(self, task: Task) -> None:
        self._tasks[task.id] = replace(task)

    async def get(self, task_id: uuid.UUID) -> Task | None:
        task = self._tasks.get(task_id)
        return None if task is None else replace(task)

    async def list(self) -> Sequence[Task]:
        newest_first = sorted(
            self._tasks.values(), key=lambda task: (task.created_at, task.id), reverse=True
        )
        return [replace(task) for task in newest_first]

    async def update(self, task: Task) -> None:
        if task.id not in self._tasks:
            raise TaskNotFound(task.id)
        self._tasks[task.id] = replace(task)

    async def delete(self, task_id: uuid.UUID) -> None:
        if task_id not in self._tasks:
            raise TaskNotFound(task_id)
        del self._tasks[task_id]
