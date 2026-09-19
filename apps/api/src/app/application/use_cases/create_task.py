import uuid
from collections.abc import Callable
from datetime import date

from app.application.clock import Clock, utc_now
from app.application.ports.task_repository import TaskRepository
from app.domain.task import Task


class CreateTask:
    def __init__(
        self,
        tasks: TaskRepository,
        *,
        clock: Clock = utc_now,
        new_id: Callable[[], uuid.UUID] = uuid.uuid4,
    ) -> None:
        self._tasks = tasks
        self._clock = clock
        self._new_id = new_id

    async def execute(
        self,
        *,
        title: str,
        created_by: uuid.UUID,
        description: str | None = None,
        due_date: date | None = None,
        assignee_id: uuid.UUID | None = None,
    ) -> Task:
        """Raises ``InvalidTaskError`` when the task would break a domain rule."""
        task = Task.create(
            task_id=self._new_id(),
            title=title,
            description=description,
            due_date=due_date,
            created_by=created_by,
            assignee_id=assignee_id,
            now=self._clock(),
        )
        await self._tasks.add(task)
        return task
