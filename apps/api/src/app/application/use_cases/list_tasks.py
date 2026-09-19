from collections.abc import Sequence

from app.application.ports.task_repository import TaskRepository
from app.domain.task import Task


class ListTasks:
    def __init__(self, tasks: TaskRepository) -> None:
        self._tasks = tasks

    async def execute(self) -> Sequence[Task]:
        return await self._tasks.list()
