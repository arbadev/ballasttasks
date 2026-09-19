from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.dependencies import ContainerDep, GetTaskDep
from app.api.rate_limit import TOO_MANY_REQUESTS, limit_requests
from app.api.routes.tasks import TaskReference
from app.api.schemas.errors import ErrorResponse
from app.api.schemas.step_generations import StepGenerationResponse
from app.api.security import get_current_user_id

router = APIRouter(
    prefix="/tasks/{id_or_key}/step-generations",
    tags=["steps"],
    dependencies=[Depends(limit_requests), Depends(get_current_user_id)],
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Unknown task or retained generation"},
        503: {"model": ErrorResponse, "description": "Generation queue unavailable; retry later"},
        **TOO_MANY_REQUESTS,
    },
)


@router.post(
    "",
    status_code=202,
    response_model=StepGenerationResponse,
    summary="Queue draft step titles without adding steps",
)
async def start(
    reference: TaskReference, get_task: GetTaskDep, container: ContainerDep
) -> StepGenerationResponse:
    task = await get_task.execute(reference)
    return StepGenerationResponse.model_validate(await container.step_generations.start(task.id))


@router.get(
    "/{job_id}", response_model=StepGenerationResponse, summary="Poll a task's retained generation"
)
async def poll(
    reference: TaskReference, job_id: UUID, get_task: GetTaskDep, container: ContainerDep
) -> StepGenerationResponse:
    task = await get_task.execute(reference)
    return StepGenerationResponse.model_validate(
        await container.step_generations.poll(task.id, job_id)
    )
