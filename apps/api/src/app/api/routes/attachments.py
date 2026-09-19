"""Attachments of a task: links and files.

Any authenticated user can attach to and remove from any task (one shared workspace), as
with the task routes. The task is addressed by its id or its key, as everywhere.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, status

from app.api.dependencies import AttachLinkDep, RemoveAttachmentDep
from app.api.rate_limit import TOO_MANY_REQUESTS, limit_requests
from app.api.routes.tasks import TaskId
from app.api.schemas.attachments import AttachmentResponse, LinkCreate
from app.api.schemas.errors import ErrorResponse
from app.api.security import CurrentUserId, get_current_user_id

TASK_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponse,
        "description": "No task has that id or key",
    }
}
NOT_FOUND: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponse,
        "description": "No task has that id or key, or the task has no such attachment",
    }
}

router = APIRouter(
    prefix="/tasks/{id_or_key}/attachments",
    tags=["attachments"],
    # The limiter first: a caller over the limit gets 429 whatever else is wrong.
    dependencies=[Depends(limit_requests), Depends(get_current_user_id)],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "Not authenticated"},
        **TOO_MANY_REQUESTS,
    },
)


@router.post(
    "/links",
    summary="Attach a link to a task",
    description=(
        "Only absolute `http` and `https` URLs. Without a `name` the link is named after its "
        "host. Attaching touches the task's `updated_at`."
    ),
    status_code=status.HTTP_201_CREATED,
    response_model=AttachmentResponse,
    responses={**TASK_NOT_FOUND},
)
async def attach_link(
    task_id: TaskId, body: LinkCreate, user_id: CurrentUserId, attach_link: AttachLinkDep
) -> AttachmentResponse:
    link = await attach_link.execute(task_id, url=body.url, name=body.name, created_by=user_id)
    return AttachmentResponse.of(link)


@router.delete(
    "/{attachment_id}",
    summary="Remove an attachment from a task",
    description="A link is forgotten; a file is also deleted from the storage.",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**NOT_FOUND},
)
async def remove_attachment(
    task_id: TaskId, attachment_id: uuid.UUID, remove_attachment: RemoveAttachmentDep
) -> None:
    await remove_attachment.execute(task_id, attachment_id)
