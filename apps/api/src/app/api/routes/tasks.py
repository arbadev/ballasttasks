"""Tasks: CRUD, the filtered list and the numbers around it.

Any authenticated user can read and change any task (one shared workspace). A task is
addressed by its id or by its key (``BT-04``, in any case and padding).
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import (
    AssessAttentionDep,
    CreateTaskDep,
    DeleteTaskDep,
    GetTaskDep,
    ListStepsDep,
    ListTasksDep,
    SummariseTasksDep,
    TallyTasksDep,
    UpdateTaskDep,
)
from app.api.rate_limit import TOO_MANY_REQUESTS, limit_requests
from app.api.schemas.errors import ErrorResponse
from app.api.schemas.tasks import (
    TaskCreate,
    TaskDetailResponse,
    TaskFilterParams,
    TaskListParams,
    TaskListResponse,
    TaskResponse,
    TaskSummaryResponse,
    TaskUpdate,
)
from app.api.security import CurrentUserId, get_current_user_id
from app.application.ports.task_tallies import TaskTally
from app.application.use_cases.get_task import parse_task_reference
from app.domain.task_key import TaskKey

NOT_FOUND: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponse,
        "description": "No task has that id or key",
    }
}

router = APIRouter(
    prefix="/tasks",
    tags=["tasks"],
    # The limiter first: a caller over the limit gets 429 whatever else is wrong.
    dependencies=[Depends(limit_requests), Depends(get_current_user_id)],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "Not authenticated"},
        **TOO_MANY_REQUESTS,
    },
)


def task_reference(id_or_key: str) -> uuid.UUID | TaskKey:
    """``422`` (``InvalidTaskReferenceError``) when it is neither an id nor a key."""
    return parse_task_reference(id_or_key)


TaskReference = Annotated[uuid.UUID | TaskKey, Depends(task_reference)]


async def task_id_of(reference: TaskReference, get_task: GetTaskDep) -> uuid.UUID:
    """The id behind a reference: a key costs one lookup, an id costs none."""
    if isinstance(reference, uuid.UUID):
        return reference
    return (await get_task.execute(reference)).id


TaskId = Annotated[uuid.UUID, Depends(task_id_of)]


@router.post(
    "",
    summary="Create a task",
    description=(
        "The task gets the next key of its project (`BT-01`, `BT-02`, ...). Without a "
        "`project_id` it lands in the Inbox."
    ),
    status_code=status.HTTP_201_CREATED,
    response_model=TaskResponse,
)
async def create_task(
    body: TaskCreate,
    user_id: CurrentUserId,
    create_task: CreateTaskDep,
    attention: AssessAttentionDep,
) -> TaskResponse:
    task = await create_task.execute(
        title=body.title,
        description=body.description,
        due_date=body.due_date,
        assignee_id=body.assignee_id,
        project_id=body.project_id,
        status=body.status,
        priority=body.priority,
        importance=body.importance,
        created_by=user_id,
    )
    # A task that has just been created has no steps and no comments: nothing to count.
    return TaskResponse.of(task, attention.execute(task), TaskTally())


@router.get(
    "",
    summary="List tasks: filtered, sorted and paged by the database",
    description=(
        "Defaults to the design's view: open tasks, most urgent first, 50 per page. Every "
        "filter narrows the result; `total` counts what matches, whatever the page. Dates "
        "are evaluated on the current UTC date."
    ),
    response_model=TaskListResponse,
)
async def list_tasks(
    params: Annotated[TaskListParams, Query()],
    user_id: CurrentUserId,
    list_tasks: ListTasksDep,
    attention: AssessAttentionDep,
    tally_tasks: TallyTasksDep,
) -> TaskListResponse:
    query = params.to_query(user_id)
    page = await list_tasks.execute(query)
    # One statement for the whole page, never one per task.
    tallies = await tally_tasks.execute([task.id for task in page.items])
    items = [
        TaskResponse.of(task, attention.execute(task), tallies[task.id]) for task in page.items
    ]
    return TaskListResponse.of(page, query, items)


# Declared before "/{id_or_key}", so "summary" is never read as a task reference.
@router.get(
    "/summary",
    summary="The numbers around the list: sidebar counts and Attention signals",
    description=(
        "`counts` and `projects` describe the open tasks of the whole workspace, whatever is "
        "filtered. `signals` describes the open tasks the filters select; `status` and "
        "`signal` are accepted and ignored there, so the same query string as the list can be "
        "sent, and choosing one chip never blanks the others."
    ),
    response_model=TaskSummaryResponse,
)
async def summarise_tasks(
    params: Annotated[TaskFilterParams, Query()],
    user_id: CurrentUserId,
    summarise_tasks: SummariseTasksDep,
) -> TaskSummaryResponse:
    summary = await summarise_tasks.execute(params.to_filter(user_id), viewer_id=user_id)
    return TaskSummaryResponse.of(summary)


@router.get(
    "/{id_or_key}",
    summary="Get one task by its id or its key, with its steps",
    response_model=TaskDetailResponse,
    responses={**NOT_FOUND},
)
async def get_task(
    reference: TaskReference,
    get_task: GetTaskDep,
    attention: AssessAttentionDep,
    tally_tasks: TallyTasksDep,
    list_steps: ListStepsDep,
) -> TaskDetailResponse:
    task = await get_task.execute(reference)
    tallies = await tally_tasks.execute([task.id])
    steps = await list_steps.execute(task.id)
    return TaskDetailResponse.with_steps(task, attention.execute(task), tallies[task.id], steps)


@router.patch(
    "/{id_or_key}",
    summary="Change a task: edit it, assign it, move it, or complete it with status=done",
    response_model=TaskResponse,
    responses={**NOT_FOUND},
)
async def update_task(
    task_id: TaskId,
    body: TaskUpdate,
    user_id: CurrentUserId,
    update_task: UpdateTaskDep,
    attention: AssessAttentionDep,
    tally_tasks: TallyTasksDep,
) -> TaskResponse:
    task = await update_task.execute(task_id, body.to_changes(), actor_id=user_id)
    tallies = await tally_tasks.execute([task.id])
    return TaskResponse.of(task, attention.execute(task), tallies[task.id])


@router.delete(
    "/{id_or_key}",
    summary="Delete a task",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**NOT_FOUND},
)
async def delete_task(task_id: TaskId, delete_task: DeleteTaskDep) -> None:
    await delete_task.execute(task_id)
