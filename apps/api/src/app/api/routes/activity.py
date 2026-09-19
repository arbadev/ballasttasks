"""A task's activity: the timeline (``/activity``) and the comments people add to it
(``/comments``). Log entries are written by the use cases, never here; comments are
immutable, so there is no route that edits or deletes one.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import ListActivityDep, PostCommentDep
from app.api.rate_limit import TOO_MANY_REQUESTS, limit_requests
from app.api.routes.tasks import NOT_FOUND, TaskId
from app.api.schemas.activity import (
    ActivityEntryResponse,
    ActivityListResponse,
    ActivityParams,
    CommentCreate,
)
from app.api.schemas.errors import ErrorResponse
from app.api.security import CurrentUserId, get_current_user_id

router = APIRouter(
    prefix="/tasks/{id_or_key}",
    tags=["activity"],
    # The limiter first: a caller over the limit gets 429 whatever else is wrong.
    dependencies=[Depends(limit_requests), Depends(get_current_user_id)],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "Not authenticated"},
        **NOT_FOUND,
        **TOO_MANY_REQUESTS,
    },
)


@router.post(
    "/comments",
    summary="Comment on a task",
    description="The comment joins the task's activity as an entry by the caller.",
    status_code=status.HTTP_201_CREATED,
    response_model=ActivityEntryResponse,
)
async def post_comment(
    task_id: TaskId, body: CommentCreate, user_id: CurrentUserId, post_comment: PostCommentDep
) -> ActivityEntryResponse:
    item = await post_comment.execute(task_id, text=body.text, actor_id=user_id)
    return ActivityEntryResponse.of(item)


@router.get(
    "/activity",
    summary="The activity of a task: log entries and comments, newest first",
    response_model=ActivityListResponse,
)
async def list_activity(
    task_id: TaskId, params: Annotated[ActivityParams, Query()], list_activity: ListActivityDep
) -> ActivityListResponse:
    page = await list_activity.execute(task_id, limit=params.limit, offset=params.offset)
    return ActivityListResponse.of(page, params)
