"""Hand-written test doubles for the application ports."""

import asyncio
import uuid
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable, Collection, Mapping, Sequence
from dataclasses import replace
from datetime import date

from app.application.errors import (
    AttachmentNotFound,
    InvalidAssigneeError,
    ProjectKeyTakenError,
    ProjectNotFound,
    TaskNotFound,
    UnknownProjectError,
)
from app.application.ports.file_storage import StoredFile
from app.application.ports.project_repository import ProjectOverview
from app.application.task_query import (
    DueFilter,
    SignalCounts,
    TaskCounts,
    TaskFilter,
    TaskPage,
    TaskQuery,
    TaskScope,
    TaskSignal,
    TaskSort,
    every_status,
)
from app.domain.attachment import Attachment
from app.domain.attention import WEEK_DAYS, Attention, assess
from app.domain.project import (
    DEFAULT_PROJECT_ID,
    DEFAULT_PROJECT_KEY,
    DEFAULT_PROJECT_NAME,
    Project,
)
from app.domain.task import Task
from app.domain.task_key import TaskKey
from app.infrastructure.storage.in_memory import InMemoryFileStorage
from tests.auth_fakes import InMemoryUserRepository
from tests.builders import CREATED


class StubHealthCheck:
    def __init__(self, name: str, *, healthy: bool = True) -> None:
        self.name = name
        self._healthy = healthy

    async def check(self) -> bool:
        return self._healthy


class RaisingHealthCheck:
    def __init__(self, name: str) -> None:
        self.name = name

    async def check(self) -> bool:
        raise RuntimeError(f"{self.name} exploded")


class HangingHealthCheck:
    def __init__(self, name: str) -> None:
        self.name = name

    async def check(self) -> bool:
        await asyncio.sleep(60)
        return True


class InMemoryProjectRepository:
    """ProjectRepository fake; passes the same contract suite as the PostgreSQL adapter.

    Like a migrated database it starts with the Inbox. Open-task counts come from the task
    fake that was built on top of it (``InMemoryTaskRepository`` registers itself).
    """

    def __init__(self) -> None:
        inbox = Project.create(
            project_id=DEFAULT_PROJECT_ID,
            name=DEFAULT_PROJECT_NAME,
            key=DEFAULT_PROJECT_KEY,
            now=CREATED,
        )
        self._projects: dict[uuid.UUID, Project] = {inbox.id: inbox}
        self._next_numbers: dict[uuid.UUID, int] = {inbox.id: 1}
        self.open_tasks_in: Callable[[uuid.UUID], int] = lambda _project_id: 0

    async def add(self, project: Project) -> None:
        if any(existing.key == project.key for existing in self._projects.values()):
            raise ProjectKeyTakenError(project.key)
        self._projects[project.id] = replace(project)
        self._next_numbers[project.id] = 1

    async def get(self, project_id: uuid.UUID) -> Project | None:
        project = self._projects.get(project_id)
        return None if project is None else replace(project)

    async def get_for_update(self, project_id: uuid.UUID) -> Project | None:
        return await self.get(project_id)

    async def overview(self, project_id: uuid.UUID) -> ProjectOverview | None:
        project = await self.get(project_id)
        if project is None:
            return None
        return ProjectOverview(project, self.open_tasks_in(project_id))

    async def overviews(self) -> Sequence[ProjectOverview]:
        ordered = sorted(self._projects.values(), key=lambda p: (p.name.lower(), p.id))
        return [ProjectOverview(replace(p), self.open_tasks_in(p.id)) for p in ordered]

    async def update(self, project: Project) -> None:
        if project.id not in self._projects:
            raise ProjectNotFound(project.id)
        self._projects[project.id] = replace(project)

    async def allocate_task_key(self, project_id: uuid.UUID) -> TaskKey:
        project = self._projects.get(project_id)
        if project is None:
            raise UnknownProjectError(project_id)
        number = self._next_numbers[project_id]
        self._next_numbers[project_id] = number + 1
        return TaskKey(project.key, number)


class InMemoryTaskRepository:
    """TaskRepository fake; passes the same contract suite as the PostgreSQL adapter.

    Tasks are copied on the way in and out, as a database would, so a change is only
    stored by an explicit ``update``. It reads the users and projects fakes the way the
    ``tasks`` table references ``users`` and ``projects``: an assignee or a project that is
    not stored there is refused. Filtering and sorting use the domain's own rules, which is
    what the SQL of the real adapter is compared against.
    """

    def __init__(self, users: InMemoryUserRepository, projects: InMemoryProjectRepository) -> None:
        self.users = users
        self.projects = projects
        self._tasks: dict[uuid.UUID, Task] = {}
        # What references tasks ``ON DELETE CASCADE`` registers here (``tests/activity_fakes``).
        self.on_delete: list[Callable[[uuid.UUID], None]] = []
        projects.open_tasks_in = self._open_tasks_in

    def _open_tasks_in(self, project_id: uuid.UUID) -> int:
        return sum(1 for t in self._tasks.values() if t.is_open and t.project_id == project_id)

    async def _refuse_unknown_references(self, task: Task) -> None:
        if await self.projects.get(task.project_id) is None:
            raise UnknownProjectError(task.project_id)
        if task.assignee_id is not None and await self.users.get_by_id(task.assignee_id) is None:
            raise InvalidAssigneeError(task.assignee_id)

    def all(self) -> list[Task]:
        """Not part of the port: every stored task, newest first, for a test to look at."""
        newest_first = sorted(
            self._tasks.values(), key=lambda t: (t.created_at, t.id), reverse=True
        )
        return [replace(task) for task in newest_first]

    async def add(self, task: Task) -> None:
        await self._refuse_unknown_references(task)
        self._tasks[task.id] = replace(task)

    async def get(self, task_id: uuid.UUID) -> Task | None:
        task = self._tasks.get(task_id)
        return None if task is None else replace(task)

    async def get_by_key(self, key: TaskKey) -> Task | None:
        found = next((t for t in self._tasks.values() if t.key == str(key)), None)
        return None if found is None else replace(found)

    async def get_for_update(self, task_id: uuid.UUID) -> Task | None:
        # No transactions here, so there is never a second writer to wait for.
        return await self.get(task_id)

    async def search(self, query: TaskQuery, *, today: date) -> TaskPage:
        found = [t for t in self._tasks.values() if _matches(t, query.filter, today)]
        ordered = _sorted(found, query.sort, today)
        page = ordered[query.offset : query.offset + query.limit]
        return TaskPage(
            items=[replace(task) for task in page],
            total=len(found),
            status_totals=every_status(Counter(task.status for task in found)),
        )

    async def count_open(self, *, viewer_id: uuid.UUID, today: date) -> TaskCounts:
        open_tasks = [t for t in self._tasks.values() if t.is_open]
        return TaskCounts(
            all=len(open_tasks),
            mine=sum(1 for t in open_tasks if t.assignee_id == viewer_id),
            overdue=sum(1 for t in open_tasks if assess(t, today=today).is_overdue),
        )

    async def count_signals(self, task_filter: TaskFilter, *, today: date) -> SignalCounts:
        found = [
            assess(t, today=today) for t in self._tasks.values() if _matches(t, task_filter, today)
        ]
        return SignalCounts(
            overdue=sum(1 for a in found if a.is_overdue),
            p0_at_risk=sum(1 for a in found if a.is_p0_at_risk),
            due_soon=sum(1 for a in found if a.is_due_soon),
            needs_owner=sum(1 for a in found if a.needs_owner),
        )

    async def update(self, task: Task) -> None:
        if task.id not in self._tasks:
            raise TaskNotFound(task.id)
        await self._refuse_unknown_references(task)
        self._tasks[task.id] = replace(task)

    async def delete(self, task_id: uuid.UUID) -> None:
        if task_id not in self._tasks:
            raise TaskNotFound(task_id)
        del self._tasks[task_id]
        for forget in self.on_delete:
            forget(task_id)


class InMemoryAttachmentRepository:
    """AttachmentRepository fake; passes the same contract suite as the PostgreSQL adapter.

    It reads the tasks fake the way the ``attachments`` table references ``tasks``: an
    attachment of a task that is not stored is refused, and one whose task has been deleted
    is gone (``ON DELETE CASCADE``). Attachments are frozen, so none is copied.
    """

    def __init__(self, tasks: InMemoryTaskRepository) -> None:
        self._tasks = tasks
        self._attachments: dict[uuid.UUID, Attachment] = {}

    async def _stored(self) -> list[Attachment]:
        """Oldest first, without the attachments of tasks that no longer exist."""
        for attachment in list(self._attachments.values()):
            if await self._tasks.get(attachment.task_id) is None:
                del self._attachments[attachment.id]
        return sorted(self._attachments.values(), key=lambda a: (a.created_at, a.id))

    def all(self) -> list[Attachment]:
        """Not part of the port: every stored attachment, oldest first, for a test to look at."""
        tasks = {task.id for task in self._tasks.all()}
        kept = [a for a in self._attachments.values() if a.task_id in tasks]
        return sorted(kept, key=lambda a: (a.created_at, a.id))

    async def add(self, attachment: Attachment) -> None:
        if await self._tasks.get(attachment.task_id) is None:
            raise TaskNotFound(attachment.task_id)
        self._attachments[attachment.id] = attachment

    async def get(self, attachment_id: uuid.UUID) -> Attachment | None:
        return next((a for a in await self._stored() if a.id == attachment_id), None)

    async def list_for_task(self, task_id: uuid.UUID) -> Sequence[Attachment]:
        return [a for a in await self._stored() if a.task_id == task_id]

    async def count_by_task(self, task_ids: Collection[uuid.UUID]) -> Mapping[uuid.UUID, int]:
        stored = await self._stored()
        return {
            task_id: sum(1 for a in stored if a.task_id == task_id) for task_id in set(task_ids)
        }

    async def delete(self, attachment_id: uuid.UUID) -> None:
        if await self.get(attachment_id) is None:
            raise AttachmentNotFound(attachment_id)
        del self._attachments[attachment_id]


class UploadedFile:
    """An ``IncomingFile`` double: a client's stream, and how much of it the server asked for.

    ``fails_with`` is the client going away halfway; ``after`` is the world changing while
    it sends, such as the task being deleted.
    """

    def __init__(
        self,
        *chunks: bytes,
        name: str | None = None,
        fails_with: Exception | None = None,
        after: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.name = name
        self._chunks = chunks
        self._fails_with = fails_with
        self._after = after
        self.chunks_read = 0
        self.prepared = False

    async def prepare(self) -> None:
        self.prepared = True

    async def chunks(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            self.chunks_read += 1
            yield chunk
        if self._after is not None:
            await self._after()
        if self._fails_with is not None:
            raise self._fails_with


class RecordingFileStorage(InMemoryFileStorage):
    """The in-memory adapter, remembering every key a save was ever started under: a test
    that says "nothing was written" means not even for a moment."""

    def __init__(self) -> None:
        super().__init__()
        self.keys_ever_written: list[str] = []

    async def save(self, key: str, chunks: AsyncIterator[bytes]) -> StoredFile:
        self.keys_ever_written.append(key)
        return await super().save(key, chunks)


def _has_signal(attention: Attention, signal: TaskSignal) -> bool:
    return {
        TaskSignal.OVERDUE: attention.is_overdue,
        TaskSignal.P0_AT_RISK: attention.is_p0_at_risk,
        TaskSignal.DUE_SOON: attention.is_due_soon,
        TaskSignal.NEEDS_OWNER: attention.needs_owner,
    }[signal]


def _matches(task: Task, f: TaskFilter, today: date) -> bool:
    """``Component.filtered`` in the design (lines 540 to 565), one refusal per line."""
    attention = assess(task, today=today)
    days = attention.days_until_due
    if f.project_id is not None and task.project_id != f.project_id:
        return False
    if f.scope is TaskScope.MINE and task.assignee_id != f.viewer_id:
        return False
    if f.scope is TaskScope.OVERDUE and not attention.is_overdue:
        return False
    if f.statuses is not None and task.status not in f.statuses:
        return False
    if f.due is DueFilter.OVERDUE and not attention.is_overdue:
        return False
    # "today" and "week" look at the date alone, done tasks included (design lines 551, 552).
    if f.due is DueFilter.TODAY and days != 0:
        return False
    if f.due is DueFilter.WEEK and not (days is not None and 0 <= days < WEEK_DAYS):
        return False
    if f.due is DueFilter.NONE and task.due_date is not None:
        return False
    if f.due_before is not None and not (task.due_date and task.due_date <= f.due_before):
        return False
    if f.due_after is not None and not (task.due_date and task.due_date >= f.due_after):
        return False
    if f.priorities is not None and task.priority not in f.priorities:
        return False
    if f.unassigned and task.assignee_id is not None:
        return False
    if f.assignee_id is not None and task.assignee_id != f.assignee_id:
        return False
    if f.search is not None:
        needle = f.search.lower()
        if needle not in task.title.lower() and needle not in (task.description or "").lower():
            return False
    return f.signal is None or _has_signal(attention, f.signal)


def _sorted(tasks: list[Task], sort: TaskSort, today: date) -> list[Task]:
    """Every order ends newest first (``created_at``, then ``id``), so pages never overlap."""
    newest_first = sorted(tasks, key=lambda t: (t.created_at, t.id), reverse=True)
    if sort is TaskSort.URGENCY:
        return sorted(newest_first, key=lambda t: -assess(t, today=today).urgency)
    if sort is TaskSort.IMPORTANCE:
        return sorted(newest_first, key=lambda t: -t.importance)
    if sort is TaskSort.DUE_DATE:
        return sorted(
            newest_first,
            key=lambda t: (t.due_date is None, t.due_date or date.max, -t.importance),
        )
    return sorted(newest_first, key=lambda t: t.updated_at, reverse=True)
