import uuid
from collections.abc import Callable

from app.application.clock import Clock, utc_now
from app.application.errors import TaskNotFound
from app.application.ports.activity_feed import ActivityItem
from app.application.ports.activity_recorder import ActivityRecorder
from app.application.ports.task_repository import TaskRepository
from app.application.ports.user_directory import UserDirectory
from app.domain import activity_log
from app.domain.activity import ActivityEntry, Actor


class PostComment:
    """Appends a comment by the caller to a task's activity. Comments are immutable: there
    is no use case that edits or deletes one."""

    def __init__(
        self,
        tasks: TaskRepository,
        activity: ActivityRecorder,
        users: UserDirectory,
        *,
        clock: Clock = utc_now,
        new_id: Callable[[], uuid.UUID] = uuid.uuid4,
    ) -> None:
        self._tasks = tasks
        self._activity = activity
        self._users = users
        self._clock = clock
        self._new_id = new_id

    async def execute(self, task_id: uuid.UUID, *, text: str, actor_id: uuid.UUID) -> ActivityItem:
        """Raises ``TaskNotFound``, or ``InvalidActivityError`` before anything is stored."""
        task = await self._tasks.get_for_update(task_id)
        if task is None:
            raise TaskNotFound(task_id)
        now = self._clock()
        entry = ActivityEntry.comment(
            entry_id=self._new_id(), task_id=task_id, actor_id=actor_id, text=text, now=now
        )
        await self._activity.record(entry)
        # As in the design's ``postComment``: a comment counts as an update of the task.
        task.touch(now)
        await self._tasks.update(task)
        full_name = await self._users.full_name_of(actor_id) or activity_log.UNKNOWN_PERSON
        return ActivityItem(entry, Actor(id=actor_id, full_name=full_name))
