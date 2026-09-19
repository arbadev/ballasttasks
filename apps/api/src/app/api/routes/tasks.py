"""Task CRUD. Any authenticated user can read and change any task (a shared team list)."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, status

from app.api.dependencies import (
    CreateTaskDep,
    DeleteTaskDep,
    GetTaskDep,
    ListTasksDep,
    UpdateTaskDep,
)
from app.api.schemas.errors import ErrorResponse
from app.api.schemas.tasks import TaskCreate, TaskListResponse, TaskResponse, TaskUpdate
from app.api.security import CurrentUserId, get_current_user_id

NOT_FOUND: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "No task has that id"}
}

router = APIRouter(
    prefix="/tasks",
    tags=["tasks"],
    dependencies=[Depends(get_current_user_id)],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "Not authenticated"}
    },
)


@router.post(
    "",
    summary="Create a task",
    status_code=status.HTTP_201_CREATED,
    response_model=TaskResponse,
)
async def create_task(
    body: TaskCreate, user_id: CurrentUserId, create_task: CreateTaskDep
) -> TaskResponse:
    task = await create_task.execute(
        title=body.title,
        description=body.description,
        due_date=body.due_date,
        assignee_id=body.assignee_id,
        created_by=user_id,
    )
    return TaskResponse.model_validate(task)


@router.get("", summary="List every task, newest first", response_model=TaskListResponse)
async def list_tasks(list_tasks: ListTasksDep) -> TaskListResponse:
    tasks = await list_tasks.execute()
    return TaskListResponse(items=[TaskResponse.model_validate(task) for task in tasks])


@router.get(
    "/{task_id}", summary="Get one task", response_model=TaskResponse, responses={**NOT_FOUND}
)
async def get_task(task_id: uuid.UUID, get_task: GetTaskDep) -> TaskResponse:
    return TaskResponse.model_validate(await get_task.execute(task_id))


@router.patch(
    "/{task_id}",
    summary="Change a task: edit it, assign it, or complete it with status=done",
    response_model=TaskResponse,
    responses={**NOT_FOUND},
)
async def update_task(
    task_id: uuid.UUID, body: TaskUpdate, update_task: UpdateTaskDep
) -> TaskResponse:
    return TaskResponse.model_validate(await update_task.execute(task_id, body.to_changes()))


@router.delete(
    "/{task_id}",
    summary="Delete a task",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**NOT_FOUND},
)
async def delete_task(task_id: uuid.UUID, delete_task: DeleteTaskDep) -> None:
    await delete_task.execute(task_id)
