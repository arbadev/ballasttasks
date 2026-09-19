"""HTTP contract for a task's activity: the log the API writes and the comments people do."""

import uuid
from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.application.ports.activity_feed import (
    DEFAULT_ACTIVITY_LIMIT,
    MAX_ACTIVITY_LIMIT,
    ActivityItem,
    ActivityPage,
)
from app.domain.activity import ACTIVITY_TEXT_MAX_LENGTH, ActivityKind

CommentText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=ACTIVITY_TEXT_MAX_LENGTH),
    Field(description="1 to 2000 characters once trimmed."),
]


class CommentCreate(BaseModel):
    """The author is the authenticated user; it is never read from the body."""

    model_config = ConfigDict(extra="forbid")

    text: CommentText


class ActivityParams(BaseModel):
    """Unknown parameters are rejected rather than silently ignored, as on the task list."""

    model_config = ConfigDict(extra="forbid")

    limit: int = Field(
        default=DEFAULT_ACTIVITY_LIMIT, ge=1, le=MAX_ACTIVITY_LIMIT, description="Page size."
    )
    offset: int = Field(default=0, ge=0, description="How many entries to skip.")


class ActorResponse(BaseModel):
    """Who an entry is by. Never an email, and the user may since have been deactivated."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    initials: str


class ActivityEntryResponse(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    kind: ActivityKind = Field(
        description="`log`: written by the API when something happened. `comment`: by a person."
    )
    text: str
    actor: ActorResponse
    created_at: datetime

    @classmethod
    def of(cls, item: ActivityItem) -> Self:
        entry = item.entry
        return cls(
            id=entry.id,
            task_id=entry.task_id,
            kind=entry.kind,
            text=entry.text,
            actor=ActorResponse.model_validate(item.actor),
            created_at=entry.created_at,
        )


class ActivityListResponse(BaseModel):
    """An envelope like the task list: ``total`` counts every entry, whatever the page."""

    items: list[ActivityEntryResponse]
    total: int
    limit: int
    offset: int

    @classmethod
    def of(cls, page: ActivityPage, params: ActivityParams) -> Self:
        return cls(
            items=[ActivityEntryResponse.of(item) for item in page.items],
            total=page.total,
            limit=params.limit,
            offset=params.offset,
        )
