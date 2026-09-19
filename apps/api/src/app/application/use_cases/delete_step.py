import uuid

from app.application.clock import Clock, utc_now
from app.application.errors import StepNotFound, TaskNotFound
from app.application.ports.step_repository import StepRepository
from app.application.ports.task_repository import TaskRepository
from app.domain.step import close_gap


class DeleteStep:
    """Removes a step and moves the ones after it up, so positions stay ``0 .. n-1``."""

    def __init__(
        self, tasks: TaskRepository, steps: StepRepository, *, clock: Clock = utc_now
    ) -> None:
        self._tasks = tasks
        self._steps = steps
        self._clock = clock

    async def execute(self, task_id: uuid.UUID, step_id: uuid.UUID) -> None:
        """Raises ``TaskNotFound``, or ``StepNotFound`` (also for a step of another task)."""
        task = await self._tasks.get_for_update(task_id)
        if task is None:
            raise TaskNotFound(task_id)
        steps = list(await self._steps.list_for_task(task_id))
        removed = next((step for step in steps if step.id == step_id), None)
        if removed is None:
            raise StepNotFound(step_id)
        steps.remove(removed)
        await self._steps.delete(removed.id)
        for step in close_gap(steps, removed):
            await self._steps.update(step)
        task.touch(self._clock())
        await self._tasks.update(task)
