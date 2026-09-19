import uuid
from collections.abc import Callable

from app.application.clock import Clock, utc_now
from app.application.errors import TaskNotFound
from app.application.ports.activity_recorder import ActivityRecorder
from app.application.ports.step_repository import StepRepository
from app.application.ports.task_repository import TaskRepository
from app.domain import activity_log
from app.domain.activity import ActivityEntry
from app.domain.step import Step


class AddStep:
    """Adds one step at the end of a task's list, as typing into the panel does.

    Like every use case that writes steps it takes the task with ``get_for_update`` first:
    whoever else is writing the steps of this task waits, so the position it computes from
    the list it read is still free when it stores it.
    """

    def __init__(
        self,
        tasks: TaskRepository,
        steps: StepRepository,
        activity: ActivityRecorder,
        *,
        clock: Clock = utc_now,
        new_id: Callable[[], uuid.UUID] = uuid.uuid4,
    ) -> None:
        self._tasks = tasks
        self._steps = steps
        self._activity = activity
        self._clock = clock
        self._new_id = new_id

    async def execute(self, task_id: uuid.UUID, *, title: str, actor_id: uuid.UUID) -> Step:
        """Raises ``TaskNotFound``, or ``InvalidStepError`` before anything is stored."""
        task = await self._tasks.get_for_update(task_id)
        if task is None:
            raise TaskNotFound(task_id)
        now = self._clock()
        existing = await self._steps.list_for_task(task_id)
        step = Step.create(
            step_id=self._new_id(), task_id=task_id, title=title, position=len(existing), now=now
        )
        await self._steps.add(step)
        task.touch(now)
        await self._tasks.update(task)
        await self._activity.record(
            ActivityEntry.log(
                entry_id=self._new_id(),
                task_id=task_id,
                actor_id=actor_id,
                text=activity_log.step_added(step.title),
                now=now,
            )
        )
        return step
