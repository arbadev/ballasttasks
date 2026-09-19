"""HTTP contract for the task endpoints.

Lengths are repeated here only so they show up in OpenAPI; the rules themselves live in
``app.domain.task`` and a request that slips past these models is still rejected there.
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.json_schema import SkipJsonSchema

from app.application.use_cases.update_task import TaskChanges
from app.domain.task import DESCRIPTION_MAX_LENGTH, TITLE_MAX_LENGTH, TaskStatus

Title = Annotated[str, Field(min_length=1, max_length=TITLE_MAX_LENGTH)]
AssigneeId = Annotated[
    uuid.UUID | None,
    Field(
        description=(
            "Id of the active user the task is assigned to; `null` leaves it unassigned. "
            "An id that is not an active user is rejected with `422`."
        )
    ),
]
UpdatedAssigneeId = Annotated[
    uuid.UUID | None,
    Field(
        description=(
            "Id of the active user the task is assigned to; `null` unassigns it. Checked only "
            "when it changes the assignment: an id that is not an active user is rejected with "
            "`422`, but the id the task already has is accepted even if that user has since "
            "been deactivated."
        )
    ),
]


class TaskCreate(BaseModel):
    """``created_by`` is the authenticated user; it is never read from the body."""

    model_config = ConfigDict(extra="forbid")

    title: Title
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    due_date: date | None = None
    assignee_id: AssigneeId = None


class TaskUpdate(BaseModel):
    """Partial update: a field that is absent is left alone, ``null`` clears it.

    ``title`` and ``status`` cannot be cleared, so ``null`` is rejected for them and
    kept out of their JSON schema.
    """

    model_config = ConfigDict(extra="forbid")

    title: Title | SkipJsonSchema[None] = None
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    status: TaskStatus | SkipJsonSchema[None] = None
    due_date: date | None = None
    assignee_id: UpdatedAssigneeId = None

    @model_validator(mode="after")
    def _required_fields_cannot_be_null(self) -> Self:
        for name in ("title", "status"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self

    def to_changes(self) -> TaskChanges:
        return TaskChanges(**{name: getattr(self, name) for name in self.model_fields_set})


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    status: TaskStatus
    due_date: date | None
    created_by: uuid.UUID
    assignee_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class TaskListResponse(BaseModel):
    """An envelope, so pagination can add fields without breaking clients."""

    items: list[TaskResponse]
