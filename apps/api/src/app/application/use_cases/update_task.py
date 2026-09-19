import uuid
from dataclasses import dataclass
from datetime import date

from app.application.clock import Clock, utc_now
from app.application.errors import InvalidAssigneeError, TaskNotFound, UnknownProjectError
from app.application.ports.project_repository import ProjectRepository
from app.application.ports.task_repository import TaskRepository
from app.application.ports.user_directory import UserDirectory
from app.application.unset import UNSET, Unset
from app.domain.task import Task, TaskPriority, TaskStatus

__all__ = ["UNSET", "TaskChanges", "Unset", "UpdateTask"]


@dataclass(frozen=True, slots=True)
class TaskChanges:
    """A partial update: only the fields that are set are applied."""

    title: str | Unset = UNSET
    description: str | Unset | None = UNSET
    status: TaskStatus | Unset = UNSET
    due_date: date | Unset | None = UNSET
    assignee_id: uuid.UUID | Unset | None = UNSET
    priority: TaskPriority | Unset = UNSET
    importance: int | Unset = UNSET
    project_id: uuid.UUID | Unset = UNSET


class UpdateTask:
    """Completing a task is ``status=done``; assigning it is ``assignee_id=<user id>``.

    The assignee is checked only when the assignment changes: a change that names somebody
    else must name an active user. A task whose assignee has since been deactivated can still
    be edited, completed or handed to somebody else, also by a change that names that same
    assignee again, as a client that sends the whole task back does.

    Moving a task to another project (``project_id``) keeps its key.
    """

    def __init__(
        self,
        tasks: TaskRepository,
        users: UserDirectory,
        projects: ProjectRepository,
        *,
        clock: Clock = utc_now,
    ) -> None:
        self._tasks = tasks
        self._users = users
        self._projects = projects
        self._clock = clock

    async def execute(self, task_id: uuid.UUID, changes: TaskChanges) -> Task:
        """Raises ``TaskNotFound``, or ``InvalidTaskError`` / ``InvalidAssigneeError`` /
        ``UnknownProjectError`` before anything is stored."""
        task = await self._tasks.get_for_update(task_id)
        if task is None:
            raise TaskNotFound(task_id)
        if changes == TaskChanges():
            return task

        now = self._clock()
        if changes.title is not UNSET:
            task.retitle(changes.title, now=now)
        if changes.description is not UNSET:
            task.describe(changes.description, now=now)
        if changes.status is not UNSET:
            task.move_to(changes.status, now=now)
        if changes.due_date is not UNSET:
            task.reschedule(changes.due_date, now=now)
        if changes.assignee_id is not UNSET:
            if changes.assignee_id != task.assignee_id:
                await self._require_active_user(changes.assignee_id)
            task.assign_to(changes.assignee_id, now=now)
        if changes.priority is not UNSET:
            task.prioritise(changes.priority, now=now)
        if changes.importance is not UNSET:
            task.weigh(changes.importance, now=now)
        if changes.project_id is not UNSET:
            if changes.project_id != task.project_id:
                await self._require_project(changes.project_id)
            task.move_to_project(changes.project_id, now=now)

        await self._tasks.update(task)
        return task

    async def _require_active_user(self, assignee_id: uuid.UUID | None) -> None:
        if assignee_id is not None and not await self._users.is_active_user(assignee_id):
            raise InvalidAssigneeError(assignee_id)

    async def _require_project(self, project_id: uuid.UUID) -> None:
        if await self._projects.get(project_id) is None:
            raise UnknownProjectError(project_id)
