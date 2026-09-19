import uuid

from app.application.errors import InvalidTaskReferenceError, TaskNotFound
from app.application.ports.task_repository import TaskRepository
from app.domain.task import Task
from app.domain.task_key import InvalidTaskKeyError, TaskKey


def parse_task_reference(text: str) -> uuid.UUID | TaskKey:
    """What a person puts after ``/tasks/``: the id, or the key in any case and padding.

    Raises ``InvalidTaskReferenceError``.
    """
    try:
        return uuid.UUID(text)
    except ValueError:
        pass
    try:
        return TaskKey.parse(text)
    except InvalidTaskKeyError:
        raise InvalidTaskReferenceError(text) from None


class GetTask:
    def __init__(self, tasks: TaskRepository) -> None:
        self._tasks = tasks

    async def execute(self, reference: uuid.UUID | TaskKey) -> Task:
        """Raises ``TaskNotFound``."""
        if isinstance(reference, TaskKey):
            task = await self._tasks.get_by_key(reference)
        else:
            task = await self._tasks.get(reference)
        if task is None:
            raise TaskNotFound(reference)
        return task
