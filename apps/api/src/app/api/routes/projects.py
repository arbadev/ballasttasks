"""Projects: what tasks belong to, and where their keys come from.

Any authenticated user can create and change any project (one shared workspace). Projects
are not deleted: every task keeps pointing at one.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, status

from app.api.dependencies import (
    CreateProjectDep,
    GetProjectDep,
    ListProjectsDep,
    UpdateProjectDep,
)
from app.api.schemas.errors import ErrorResponse
from app.api.schemas.projects import (
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
)
from app.api.security import get_current_user_id

NOT_FOUND: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "No project has that id"}
}

router = APIRouter(
    prefix="/projects",
    tags=["projects"],
    dependencies=[Depends(get_current_user_id)],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "Not authenticated"}
    },
)


@router.post(
    "",
    summary="Create a project",
    status_code=status.HTTP_201_CREATED,
    response_model=ProjectResponse,
    responses={
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "Another project already has that key",
        }
    },
)
async def create_project(body: ProjectCreate, create_project: CreateProjectDep) -> ProjectResponse:
    overview = await create_project.execute(name=body.name, key=body.key, color=body.color)
    return ProjectResponse.of(overview)


@router.get(
    "",
    summary="List every project, by name, with its open-task count",
    response_model=ProjectListResponse,
)
async def list_projects(list_projects: ListProjectsDep) -> ProjectListResponse:
    overviews = await list_projects.execute()
    return ProjectListResponse(items=[ProjectResponse.of(overview) for overview in overviews])


@router.get(
    "/{project_id}",
    summary="Get one project",
    response_model=ProjectResponse,
    responses={**NOT_FOUND},
)
async def get_project(project_id: uuid.UUID, get_project: GetProjectDep) -> ProjectResponse:
    return ProjectResponse.of(await get_project.execute(project_id))


@router.patch(
    "/{project_id}",
    summary="Rename or recolour a project; its key is fixed",
    response_model=ProjectResponse,
    responses={**NOT_FOUND},
)
async def update_project(
    project_id: uuid.UUID, body: ProjectUpdate, update_project: UpdateProjectDep
) -> ProjectResponse:
    return ProjectResponse.of(await update_project.execute(project_id, body.to_changes()))
