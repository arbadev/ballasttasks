import uuid
from collections.abc import Callable
from datetime import date

from app.application.clock import Clock, utc_now
from app.application.errors import InvalidAssigneeError
from app.application.ports.project_repository import ProjectRepository
from app.application.ports.task_repository import TaskRepository
from app.application.ports.user_directory import UserDirectory
from app.domain.project import DEFAULT_PROJECT_ID
from app.domain.task import DEFAULT_IMPORTANCE, DEFAULT_PRIORITY, Task, TaskPriority, TaskStatus


class CreateTask:
    def __init__(
        self,
        tasks: TaskRepository,
        users: UserDirectory,
        projects: ProjectRepository,
        *,
        clock: Clock = utc_now,
        new_id: Callable[[], uuid.UUID] = uuid.uuid4,
    ) -> None:
        self._tasks = tasks
        self._users = users
        self._projects = projects
        self._clock = clock
        self._new_id = new_id

    async def execute(
        self,
        *,
        title: str,
        created_by: uuid.UUID,
        project_id: uuid.UUID | None = None,
        description: str | None = None,
        status: TaskStatus = TaskStatus.TODO,
        due_date: date | None = None,
        assignee_id: uuid.UUID | None = None,
        priority: TaskPriority = DEFAULT_PRIORITY,
        importance: int = DEFAULT_IMPORTANCE,
    ) -> Task:
        """A task without a project lands in the Inbox, as in the design.

        Raises ``InvalidTaskError`` when the task would break a domain rule,
        ``InvalidAssigneeError`` when the assignee is not an active user, and
        ``UnknownProjectError`` when the project does not exist.
        """
        target = project_id or DEFAULT_PROJECT_ID
        # Taking a key locks the project's counter until the unit of work ends. Whatever is
        # refused below costs no number: the rollback gives it back.
        key = await self._projects.allocate_task_key(target)
        task = Task.create(
            task_id=self._new_id(),
            title=title,
            description=description,
            status=status,
            due_date=due_date,
            created_by=created_by,
            assignee_id=assignee_id,
            project_id=target,
            key=key,
            priority=priority,
            importance=importance,
            now=self._clock(),
        )
        # After the domain rules, so a task that breaks one is reported as that, whoever it
        # was meant for.
        if assignee_id is not None and not await self._users.is_active_user(assignee_id):
            raise InvalidAssigneeError(assignee_id)
        await self._tasks.add(task)
        return task
