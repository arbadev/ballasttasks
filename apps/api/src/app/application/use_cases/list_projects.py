from collections.abc import Sequence

from app.application.ports.project_repository import ProjectOverview, ProjectRepository


class ListProjects:
    def __init__(self, projects: ProjectRepository) -> None:
        self._projects = projects

    async def execute(self) -> Sequence[ProjectOverview]:
        return await self._projects.overviews()
