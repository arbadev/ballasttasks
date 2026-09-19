import uuid
from collections.abc import Callable, Sequence

from app.application.clock import Clock, utc_now
from app.application.errors import TaskNotFound
from app.application.ports.activity_recorder import ActivityRecorder
from app.application.ports.step_repository import StepRepository
from app.application.ports.task_repository import TaskRepository
from app.application.ports.user_directory import UserDirectory
from app.domain import activity_log
from app.domain.activity import ActivityEntry
from app.domain.step import InvalidStepError, Step, check_room_for

MAX_STEPS_AT_ONCE = 20


class AddSteps:
    """Adds several steps at the end of a task's list, all or none: how proposed steps are
    accepted (the design's ``accept``). One log line for the lot, in the design's words."""

    def __init__(
        self,
        tasks: TaskRepository,
        steps: StepRepository,
        activity: ActivityRecorder,
        users: UserDirectory,
        *,
        clock: Clock = utc_now,
        new_id: Callable[[], uuid.UUID] = uuid.uuid4,
    ) -> None:
        self._tasks = tasks
        self._steps = steps
        self._activity = activity
        self._users = users
        self._clock = clock
        self._new_id = new_id

    async def execute(
        self, task_id: uuid.UUID, *, titles: Sequence[str], actor_id: uuid.UUID
    ) -> list[Step]:
        """Raises ``TaskNotFound``, or ``InvalidStepError`` (too many or too few titles, a
        bad one, or no room for them all) before anything is stored: never a part of them."""
        if not 1 <= len(titles) <= MAX_STEPS_AT_ONCE:
            raise InvalidStepError(f"titles must hold from 1 to {MAX_STEPS_AT_ONCE} titles")
        task = await self._tasks.get_for_update(task_id)
        if task is None:
            raise TaskNotFound(task_id)
        now = self._clock()
        first_free = len(await self._steps.list_for_task(task_id))
        check_room_for(first_free, adding=len(titles))
        # Every step is built, and so checked, before the first one is stored.
        created = [
            Step.create(
                step_id=self._new_id(),
                task_id=task_id,
                title=title,
                position=first_free + offset,
                now=now,
            )
            for offset, title in enumerate(titles)
        ]
        for step in created:
            await self._steps.add(step)
        task.touch(now)
        await self._tasks.update(task)
        added_by = await self._users.full_name_of(actor_id) or activity_log.UNKNOWN_PERSON
        await self._activity.record(
            ActivityEntry.log(
                entry_id=self._new_id(),
                task_id=task_id,
                actor_id=actor_id,
                text=activity_log.steps_drafted(len(created), added_by=added_by),
                now=now,
            )
        )
        return created
