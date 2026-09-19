import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date

from app.application.clock import Clock, utc_now
from app.application.errors import InvalidAssigneeError, TaskNotFound, UnknownProjectError
from app.application.ports.activity_recorder import ActivityRecorder
from app.application.ports.project_repository import ProjectRepository
from app.application.ports.task_repository import TaskRepository
from app.application.ports.user_directory import UserDirectory
from app.application.unset import UNSET, Unset
from app.domain import activity_log
from app.domain.activity import ActivityEntry
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

    What the change leaves in the task's activity is the design's ``update(id, patch,
    logText)``, decided by ``app.domain.activity_log.changes`` from the task before and
    after: a change that alters nothing records nothing, and the lines are recorded only
    once the task has been stored, in the same unit of work.
    """

    def __init__(
        self,
        tasks: TaskRepository,
        users: UserDirectory,
        projects: ProjectRepository,
        activity: ActivityRecorder,
        *,
        clock: Clock = utc_now,
        new_id: Callable[[], uuid.UUID] = uuid.uuid4,
    ) -> None:
        self._tasks = tasks
        self._users = users
        self._projects = projects
        self._activity = activity
        self._clock = clock
        self._new_id = new_id

    async def execute(
        self, task_id: uuid.UUID, changes: TaskChanges, *, actor_id: uuid.UUID
    ) -> Task:
        """Raises ``TaskNotFound``, or ``InvalidTaskError`` / ``InvalidAssigneeError`` /
        ``UnknownProjectError`` before anything is stored."""
        task = await self._tasks.get_for_update(task_id)
        if task is None:
            raise TaskNotFound(task_id)
        if changes == TaskChanges():
            return task

        now = self._clock()
        before = replace(task)
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
        await self._record(before, task, actor_id=actor_id)
        return task

    async def _record(self, before: Task, after: Task, *, actor_id: uuid.UUID) -> None:
        assignee_name = None
        if after.assignee_id is not None and after.assignee_id != before.assignee_id:
            assignee_name = await self._users.full_name_of(after.assignee_id)
        lines = activity_log.changes(
            before,
            after,
            today=after.updated_at.astimezone(UTC).date(),
            assignee_name=assignee_name,
        )
        for text in lines:
            await self._activity.record(
                ActivityEntry.log(
                    entry_id=self._new_id(),
                    task_id=after.id,
                    actor_id=actor_id,
                    text=text,
                    now=after.updated_at,
                )
            )

    async def _require_active_user(self, assignee_id: uuid.UUID | None) -> None:
        if assignee_id is not None and not await self._users.is_active_user(assignee_id):
            raise InvalidAssigneeError(assignee_id)

    async def _require_project(self, project_id: uuid.UUID) -> None:
        if await self._projects.get(project_id) is None:
            raise UnknownProjectError(project_id)
