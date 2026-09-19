"""HTTP contract for the attachments of a task.

Lengths are repeated here only so they show up in OpenAPI; what a link may be is decided
by ``app.domain.attachment``, and a request that slips past these models is refused there.
"""

import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from app.domain.attachment import NAME_MAX_LENGTH, URL_MAX_LENGTH, Attachment, AttachmentKind


class LinkCreate(BaseModel):
    """``created_by`` is the authenticated user; the kind is ``link``: neither is read."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(
        min_length=1,
        max_length=URL_MAX_LENGTH,
        description=(
            "An absolute `http` or `https` URL with a host. Anything else is a `422`: another "
            "scheme (`javascript:`, `data:`, `file:`), a relative reference, a user name or "
            "password in the URL, whitespace or control characters."
        ),
        examples=["https://github.com/arbadev/ballasttasks"],
    )
    name: str | None = Field(
        default=None,
        max_length=NAME_MAX_LENGTH,
        description="What people see. Absent, `null` or blank: the URL's host.",
        examples=["The repository"],
    )


class FileUpload(BaseModel):
    """Multipart body documentation; parsed incrementally, never buffered by FastAPI."""

    file: bytes = Field(json_schema_extra={"format": "binary"})


class AttachmentResponse(BaseModel):
    """Where a file is stored is never part of the contract; its bytes come from
    ``GET /tasks/{id_or_key}/attachments/{attachment_id}/content``."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    kind: AttachmentKind
    name: str = Field(description="Display name: the link's name, or the file's sanitised name.")
    url: str | None = Field(description="The link's address; `null` for a file.")
    content_type: str | None = Field(
        description="What the file's leading bytes say it is; `null` for a link."
    )
    size_bytes: int | None = Field(description="Size of the stored file; `null` for a link.")
    created_by: uuid.UUID
    created_at: datetime

    @classmethod
    def of(cls, attachment: Attachment) -> Self:
        return cls.model_validate(attachment)
