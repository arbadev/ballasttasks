import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.domain.project import Project
from app.domain.task_key import TaskKey


@dataclass(frozen=True, slots=True)
class ProjectOverview:
    """A project as the sidebar shows it: with the number of its tasks that are not done."""

    project: Project
    open_tasks: int


class ProjectRepository(Protocol):
    """Stores projects and hands out task keys. Returned projects are detached: a change is
    stored only by ``update``. Every store starts with the Inbox (``DEFAULT_PROJECT_ID``)."""

    async def add(self, project: Project) -> None:
        """Store a new project.

        Raises ``ProjectKeyTakenError`` when the key is taken, including when a concurrent
        ``add`` won the race; nothing is stored and the repository stays usable.
        """
        ...

    async def get(self, project_id: uuid.UUID) -> Project | None: ...

    async def get_for_update(self, project_id: uuid.UUID) -> Project | None:
        """Like ``get``, and nobody else can change the project until the unit of work ends."""
        ...

    async def overview(self, project_id: uuid.UUID) -> ProjectOverview | None: ...

    async def overviews(self) -> Sequence[ProjectOverview]:
        """Every project, by name whatever the case, then by id."""
        ...

    async def update(self, project: Project) -> None:
        """Store the current state of an existing project. Raises ``ProjectNotFound``."""
        ...

    async def allocate_task_key(self, project_id: uuid.UUID) -> TaskKey:
        """The project's next key: 1, 2, 3, ... with no duplicate and no gap.

        The number belongs to the unit of work: a second caller for the same project waits
        until this one ends, and gets the same number when this one is rolled back. Callers
        for other projects do not wait. Raises ``UnknownProjectError``.
        """
        ...
