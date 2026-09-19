import uuid
from collections.abc import Callable
from dataclasses import dataclass

from app.application.clock import Clock, utc_now
from app.application.errors import StepNotFound, TaskNotFound
from app.application.ports.activity_recorder import ActivityRecorder
from app.application.ports.step_repository import StepRepository
from app.application.ports.task_repository import TaskRepository
from app.application.unset import UNSET, Unset
from app.domain import activity_log
from app.domain.activity import ActivityEntry
from app.domain.step import Step

__all__ = ["UNSET", "StepChanges", "Unset", "UpdateStep"]


@dataclass(frozen=True, slots=True)
class StepChanges:
    """A partial update: only the fields that are set are applied."""

    title: str | Unset = UNSET
    done: bool | Unset = UNSET


class UpdateStep:
    """Renames a step, ticks it, or both. Only a step becoming done is logged; a change
    that alters nothing stores nothing, logs nothing and leaves the task's ``updated_at``."""

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

    async def execute(
        self, task_id: uuid.UUID, step_id: uuid.UUID, changes: StepChanges, *, actor_id: uuid.UUID
    ) -> Step:
        """Raises ``TaskNotFound``, ``StepNotFound`` (also for a step of another task), or
        ``InvalidStepError`` before anything is stored."""
        task = await self._tasks.get_for_update(task_id)
        if task is None:
            raise TaskNotFound(task_id)
        step = next((s for s in await self._steps.list_for_task(task_id) if s.id == step_id), None)
        if step is None:
            raise StepNotFound(step_id)

        before = (step.title, step.done)
        if changes.title is not UNSET:
            step.rename(changes.title)
        completed = changes.done is not UNSET and step.mark(done=changes.done) and step.done
        if (step.title, step.done) == before:
            return step

        now = self._clock()
        await self._steps.update(step)
        task.touch(now)
        await self._tasks.update(task)
        if completed:
            await self._activity.record(
                ActivityEntry.log(
                    entry_id=self._new_id(),
                    task_id=task_id,
                    actor_id=actor_id,
                    text=activity_log.step_completed(step.title),
                    now=now,
                )
            )
        return step
