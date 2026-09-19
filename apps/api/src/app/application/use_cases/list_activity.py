import uuid

from app.application.errors import TaskNotFound
from app.application.ports.activity_feed import ActivityFeed, ActivityPage
from app.application.ports.task_repository import TaskRepository


class ListActivity:
    def __init__(self, tasks: TaskRepository, feed: ActivityFeed) -> None:
        self._tasks = tasks
        self._feed = feed

    async def execute(self, task_id: uuid.UUID, *, limit: int, offset: int) -> ActivityPage:
        """One page of the task's activity, newest first. Raises ``TaskNotFound``."""
        if await self._tasks.get(task_id) is None:
            raise TaskNotFound(task_id)
        return await self._feed.page(task_id, limit=limit, offset=offset)
