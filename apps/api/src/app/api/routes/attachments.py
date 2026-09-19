"""Attachments of a task: links and files.

Any authenticated user can attach to and remove from any task (one shared workspace), as
with the task routes. The task is addressed by its id or its key, as everywhere.
"""

import uuid
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse

from app.api.dependencies import (
    AttachFileDep,
    AttachLinkDep,
    GetTaskDep,
    OpenAttachmentContentDep,
    RemoveAttachmentDep,
)
from app.api.multipart import StreamingUpload
from app.api.rate_limit import TOO_MANY_REQUESTS, limit_requests
from app.api.routes.tasks import TaskId
from app.api.schemas.attachments import AttachmentResponse, FileUpload, LinkCreate
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


@router.post(
    "/files",
    status_code=201,
    response_model=AttachmentResponse,
    summary="Upload a PDF or image attachment",
    description=(
        "One multipart file. Type is determined by leading bytes, never the supplied MIME type. "
        "PDF, PNG, JPEG, GIF and WebP only. Default limit: 10 MiB, checked while streaming."
    ),
    responses={
        **TASK_NOT_FOUND,
        413: {"model": ErrorResponse, "description": "File too large"},
        415: {"model": ErrorResponse, "description": "Unsupported leading bytes"},
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"multipart/form-data": {"schema": FileUpload.model_json_schema()}},
        }
    },
)
async def attach_file(
    task_id: TaskId,
    request: Request,
    user_id: CurrentUserId,
    attach_file: AttachFileDep,
    get_task: GetTaskDep,
) -> AttachmentResponse:
    await get_task.execute(task_id)
    upload = StreamingUpload(request)
    await upload.prepare()
    attached = await attach_file.execute(
        task_id, file_name=upload.name, chunks=upload.chunks(), created_by=user_id
    )
    return AttachmentResponse.of(attached)


@router.get(
    "/{attachment_id}/content",
    response_model=None,
    response_class=StreamingResponse,
    summary="Download an attachment",
    responses={
        **NOT_FOUND,
        200: {
            "description": "Stored file, with Content-Disposition and nosniff",
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        },
    },
)
async def attachment_content(
    task_id: TaskId, attachment_id: uuid.UUID, open_content: OpenAttachmentContentDep
) -> StreamingResponse:
    attachment, chunks = await open_content.execute(task_id, attachment_id)
    disposition = f"attachment; filename*=UTF-8''{quote(attachment.name, safe='')}"
    return StreamingResponse(
        chunks,
        media_type=attachment.content_type,
        headers={
            "Content-Disposition": disposition,
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete(
    "/{attachment_id}",
    summary="Remove an attachment from a task",
    description="A link is forgotten; a file is also deleted from the storage.",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses={**NOT_FOUND},
)
async def remove_attachment(
    task_id: TaskId, attachment_id: uuid.UUID, remove_attachment: RemoveAttachmentDep
) -> None:
    await remove_attachment.execute(task_id, attachment_id)
