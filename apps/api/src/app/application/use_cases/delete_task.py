import uuid

from app.application.ports.task_repository import TaskRepository


class DeleteTask:
    def __init__(self, tasks: TaskRepository) -> None:
        self._tasks = tasks

    async def execute(self, task_id: uuid.UUID) -> None:
        """Raises ``TaskNotFound``."""
        await self._tasks.delete(task_id)
