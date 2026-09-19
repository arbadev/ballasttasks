from app.application.clock import Clock, today_utc, utc_now
from app.application.ports.task_repository import TaskRepository
from app.application.task_query import TaskPage, TaskQuery


class ListTasks:
    """Filtering, sorting and counting are the repository's work; this adds the date."""

    def __init__(self, tasks: TaskRepository, *, clock: Clock = utc_now) -> None:
        self._tasks = tasks
        self._clock = clock

    async def execute(self, query: TaskQuery) -> TaskPage:
        return await self._tasks.search(query, today=today_utc(self._clock))
