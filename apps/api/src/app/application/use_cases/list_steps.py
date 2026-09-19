import uuid
from collections.abc import Sequence

from app.application.errors import TaskNotFound
from app.application.ports.step_repository import StepRepository
from app.application.ports.task_repository import TaskRepository
from app.domain.step import Step


class ListSteps:
    def __init__(self, tasks: TaskRepository, steps: StepRepository) -> None:
        self._tasks = tasks
        self._steps = steps

    async def execute(self, task_id: uuid.UUID) -> Sequence[Step]:
        """The task's steps in order. Raises ``TaskNotFound``."""
        if await self._tasks.get(task_id) is None:
            raise TaskNotFound(task_id)
        return await self._steps.list_for_task(task_id)
