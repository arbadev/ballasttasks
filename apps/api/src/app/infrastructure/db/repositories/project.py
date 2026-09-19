import uuid
from collections.abc import Sequence

from sqlalchemy import Select, and_, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.errors import ProjectKeyTakenError, ProjectNotFound, UnknownProjectError
from app.application.ports.project_repository import ProjectOverview
from app.domain.project import Project
from app.domain.task_key import TaskKey
from app.infrastructure.db.constraints import violated_constraint
from app.infrastructure.db.models.project import KEY_UNIQUE_CONSTRAINT, ProjectModel
from app.infrastructure.db.models.task import TaskModel
from app.infrastructure.db.repositories.task_queries import IS_OPEN


class SqlAlchemyProjectRepository:
    """ProjectRepository on PostgreSQL.

    Works inside the session it is given and never commits: the transaction belongs to
    ``transactional_session`` (see ``app.infrastructure.db.unit_of_work``).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, project: Project) -> None:
        try:
            # A savepoint, so a taken key undoes only this insert and the rest of the unit of
            # work stays usable.
            async with self._session.begin_nested():
                self._session.add(
                    ProjectModel(
                        id=project.id,
                        name=project.name,
                        key=project.key,
                        color=project.color,
                        created_at=project.created_at,
                        updated_at=project.updated_at,
                    )
                )
        except IntegrityError as error:
            # The unique constraint, not a prior SELECT, is what makes this race-safe.
            if violated_constraint(error) == KEY_UNIQUE_CONSTRAINT:
                raise ProjectKeyTakenError(project.key) from error
            raise

    async def get(self, project_id: uuid.UUID) -> Project | None:
        row = await self._session.get(ProjectModel, project_id)
        return None if row is None else _to_project(row)

    async def get_for_update(self, project_id: uuid.UUID) -> Project | None:
        row = await self._session.get(
            ProjectModel, project_id, with_for_update=True, populate_existing=True
        )
        return None if row is None else _to_project(row)

    async def overview(self, project_id: uuid.UUID) -> ProjectOverview | None:
        row = (
            await self._session.execute(_overviews().where(ProjectModel.id == project_id))
        ).one_or_none()
        return None if row is None else ProjectOverview(_to_project(row[0]), row[1])

    async def overviews(self) -> Sequence[ProjectOverview]:
        """One statement for every project and its count: no query per project."""
        rows = await self._session.execute(
            # COLLATE "C": by code point, whatever locale the database was created with.
            _overviews().order_by(func.lower(ProjectModel.name).collate("C"), ProjectModel.id)
        )
        return [ProjectOverview(_to_project(project), open_tasks) for project, open_tasks in rows]

    async def update(self, project: Project) -> None:
        row = await self._session.get(ProjectModel, project.id)
        if row is None:
            raise ProjectNotFound(project.id)
        row.name, row.color, row.updated_at = project.name, project.color, project.updated_at
        await self._session.flush()

    async def allocate_task_key(self, project_id: uuid.UUID) -> TaskKey:
        """One ``UPDATE ... RETURNING`` on the project's own row (ADR 0005).

        The UPDATE takes the row lock and keeps it until the unit of work ends, so a second
        creator in the same project waits here, then reads the number the first one left. A
        rollback undoes the increment, which is why there are no gaps: a sequence would hand
        out numbers that a rolled-back transaction never uses.
        """
        row = (
            await self._session.execute(
                update(ProjectModel)
                .where(ProjectModel.id == project_id)
                .values(next_task_number=ProjectModel.next_task_number + 1)
                .returning(ProjectModel.key, ProjectModel.next_task_number - 1)
                .execution_options(synchronize_session=False)
            )
        ).one_or_none()
        if row is None:
            raise UnknownProjectError(project_id)
        return TaskKey(row[0], row[1])


def _overviews() -> Select[tuple[ProjectModel, int]]:
    # The open-task condition is part of the join, so a project with no open task still has
    # a row (count 0) and the partial index on open tasks can serve the join.
    return (
        select(ProjectModel, func.count(TaskModel.id))
        .outerjoin(TaskModel, and_(TaskModel.project_id == ProjectModel.id, IS_OPEN))
        .group_by(ProjectModel.id)
    )


def _to_project(row: ProjectModel) -> Project:
    return Project(
        id=row.id,
        name=row.name,
        key=row.key,
        color=row.color,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
