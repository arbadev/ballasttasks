import uuid

from app.application.errors import ProjectNotFound
from app.application.ports.project_repository import ProjectOverview, ProjectRepository


class GetProject:
    def __init__(self, projects: ProjectRepository) -> None:
        self._projects = projects

    async def execute(self, project_id: uuid.UUID) -> ProjectOverview:
        """Raises ``ProjectNotFound``."""
        overview = await self._projects.overview(project_id)
        if overview is None:
            raise ProjectNotFound(project_id)
        return overview
