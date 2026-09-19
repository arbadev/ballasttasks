import uuid
from dataclasses import dataclass

from app.application.clock import Clock, utc_now
from app.application.errors import ProjectNotFound
from app.application.ports.project_repository import ProjectOverview, ProjectRepository
from app.application.unset import UNSET, Unset


@dataclass(frozen=True, slots=True)
class ProjectChanges:
    """A partial update: only the fields that are set are applied.

    There is no ``key``: it is part of every key the project has handed out.
    """

    name: str | Unset = UNSET
    color: str | Unset | None = UNSET


class UpdateProject:
    def __init__(self, projects: ProjectRepository, *, clock: Clock = utc_now) -> None:
        self._projects = projects
        self._clock = clock

    async def execute(self, project_id: uuid.UUID, changes: ProjectChanges) -> ProjectOverview:
        """Raises ``ProjectNotFound``, or ``InvalidProjectError`` before anything is stored."""
        project = await self._projects.get_for_update(project_id)
        if project is None:
            raise ProjectNotFound(project_id)
        if changes != ProjectChanges():
            now = self._clock()
            if changes.name is not UNSET:
                project.rename(changes.name, now=now)
            if changes.color is not UNSET:
                project.recolor(changes.color, now=now)
            await self._projects.update(project)
        overview = await self._projects.overview(project_id)
        if overview is None:  # pragma: no cover - the row is locked by this unit of work
            raise ProjectNotFound(project_id)
        return overview
