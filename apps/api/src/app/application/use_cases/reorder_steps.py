import uuid
from collections.abc import Sequence

from app.application.clock import Clock, utc_now
from app.application.errors import TaskNotFound
from app.application.ports.step_repository import StepRepository
from app.application.ports.task_repository import TaskRepository
from app.domain.step import Step, in_order


class ReorderSteps:
    """Puts a task's steps in the order of the ids it is given, which must name every step
    exactly once. The task is held while it works, so an order built from a list that has
    changed since (a step added, a step deleted) is refused whole, never half applied."""

    def __init__(
        self, tasks: TaskRepository, steps: StepRepository, *, clock: Clock = utc_now
    ) -> None:
        self._tasks = tasks
        self._steps = steps
        self._clock = clock

    async def execute(self, task_id: uuid.UUID, step_ids: Sequence[uuid.UUID]) -> list[Step]:
        """Raises ``TaskNotFound``, or ``InvalidStepOrderError`` before anything is stored."""
        task = await self._tasks.get_for_update(task_id)
        if task is None:
            raise TaskNotFound(task_id)
        steps = await self._steps.list_for_task(task_id)
        positions_before = {step.id: step.position for step in steps}
        ordered = in_order(steps, step_ids)
        moved = [step for step in ordered if step.position != positions_before[step.id]]
        if not moved:
            return ordered
        for step in moved:
            await self._steps.update(step)
        task.touch(self._clock())
        await self._tasks.update(task)
        return ordered
