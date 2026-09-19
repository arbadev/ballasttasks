import uuid
from collections.abc import Callable

from app.application.clock import Clock, utc_now
from app.application.ports.project_repository import ProjectOverview, ProjectRepository
from app.domain.project import Project


class CreateProject:
    def __init__(
        self,
        projects: ProjectRepository,
        *,
        clock: Clock = utc_now,
        new_id: Callable[[], uuid.UUID] = uuid.uuid4,
    ) -> None:
        self._projects = projects
        self._clock = clock
        self._new_id = new_id

    async def execute(self, *, name: str, key: str, color: str | None = None) -> ProjectOverview:
        """Raises ``InvalidProjectError`` when the project would break a domain rule and
        ``ProjectKeyTakenError`` when another project has the key."""
        project = Project.create(
            project_id=self._new_id(), name=name, key=key, color=color, now=self._clock()
        )
        await self._projects.add(project)
        return ProjectOverview(project, open_tasks=0)
