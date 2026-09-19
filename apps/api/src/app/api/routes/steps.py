"""The steps (subtasks) of a task, under ``/tasks/{id_or_key}/steps``.

Same workspace rule as the tasks: any authenticated user can change the steps of any task.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, status

from app.api.dependencies import (
    AddStepDep,
    AddStepsDep,
    DeleteStepDep,
    ListStepsDep,
    ReorderStepsDep,
    UpdateStepDep,
)
from app.api.rate_limit import TOO_MANY_REQUESTS, limit_requests
from app.api.routes.tasks import NOT_FOUND, TaskId
from app.api.schemas.errors import ErrorResponse
from app.api.schemas.steps import (
    StepCreate,
    StepListResponse,
    StepResponse,
    StepsCreate,
    StepsOrder,
    StepUpdate,
)
from app.api.security import CurrentUserId, get_current_user_id
from app.domain.step import MAX_STEPS_PER_TASK

TASK_OR_STEP_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponse,
        "description": "No task has that id or key, or the task has no such step",
    }
}

router = APIRouter(
    prefix="/tasks/{id_or_key}/steps",
    tags=["steps"],
    # The limiter first: a caller over the limit gets 429 whatever else is wrong.
    dependencies=[Depends(limit_requests), Depends(get_current_user_id)],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "Not authenticated"},
        **NOT_FOUND,
        **TOO_MANY_REQUESTS,
    },
)


@router.get("", summary="The steps of a task, in order", response_model=StepListResponse)
async def list_steps(task_id: TaskId, list_steps: ListStepsDep) -> StepListResponse:
    return StepListResponse.of(await list_steps.execute(task_id))


@router.post(
    "",
    summary="Add a step at the end of the list",
    description=(
        f"A task holds at most {MAX_STEPS_PER_TASK} steps; the one after that is rejected "
        "with `422`."
    ),
    status_code=status.HTTP_201_CREATED,
    response_model=StepResponse,
)
async def add_step(
    task_id: TaskId, body: StepCreate, user_id: CurrentUserId, add_step: AddStepDep
) -> StepResponse:
    step = await add_step.execute(task_id, title=body.title, actor_id=user_id)
    return StepResponse.model_validate(step)


@router.post(
    "/bulk",
    summary="Add several steps at once, all or none",
    description=(
        "How proposed steps are accepted: up to 20 titles, appended in the order given in one "
        "transaction, and logged as one activity entry. One invalid title refuses them all, "
        f"and so does a batch that would take the task past its {MAX_STEPS_PER_TASK} steps: "
        "nothing of it is added."
    ),
    status_code=status.HTTP_201_CREATED,
    response_model=StepListResponse,
)
async def add_steps(
    task_id: TaskId, body: StepsCreate, user_id: CurrentUserId, add_steps: AddStepsDep
) -> StepListResponse:
    created = await add_steps.execute(task_id, titles=body.titles, actor_id=user_id)
    return StepListResponse.of(created)


@router.put(
    "/order",
    summary="Reorder the steps of a task",
    description="Answers every step of the task in its new order.",
    response_model=StepListResponse,
)
async def reorder_steps(
    task_id: TaskId, body: StepsOrder, reorder_steps: ReorderStepsDep
) -> StepListResponse:
    return StepListResponse.of(await reorder_steps.execute(task_id, body.step_ids))


@router.patch(
    "/{step_id}",
    summary="Rename a step, tick it or untick it",
    response_model=StepResponse,
    responses={**TASK_OR_STEP_NOT_FOUND},
)
async def update_step(
    task_id: TaskId,
    step_id: uuid.UUID,
    body: StepUpdate,
    user_id: CurrentUserId,
    update_step: UpdateStepDep,
) -> StepResponse:
    step = await update_step.execute(task_id, step_id, body.to_changes(), actor_id=user_id)
    return StepResponse.model_validate(step)


@router.delete(
    "/{step_id}",
    summary="Delete a step; the ones after it move up",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**TASK_OR_STEP_NOT_FOUND},
)
async def delete_step(task_id: TaskId, step_id: uuid.UUID, delete_step: DeleteStepDep) -> None:
    await delete_step.execute(task_id, step_id)
