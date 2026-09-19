import uuid

from app.application.errors import TaskNotFound
from app.application.ports.task_repository import TaskRepository
from app.domain.task import Task


class GetTask:
    def __init__(self, tasks: TaskRepository) -> None:
        self._tasks = tasks

    async def execute(self, task_id: uuid.UUID) -> Task:
        task = await self._tasks.get(task_id)
        if task is None:
            raise TaskNotFound(task_id)
        return task
