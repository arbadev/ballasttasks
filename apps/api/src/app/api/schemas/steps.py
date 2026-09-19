"""HTTP contract for the steps of a task.

Lengths are repeated here only so they show up in OpenAPI; the rules themselves live in
``app.domain.step`` and a request that slips past these models is still rejected there.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.application.use_cases.add_steps import MAX_STEPS_AT_ONCE
from app.application.use_cases.update_step import StepChanges
from app.domain.step import MAX_STEPS_PER_TASK, STEP_TITLE_MAX_LENGTH, Step

StepTitle = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=STEP_TITLE_MAX_LENGTH),
    Field(description="1 to 200 characters once trimmed."),
]


class StepCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: StepTitle


class StepsCreate(BaseModel):
    """Several steps accepted at once: all of them are created, in this order, or none is."""

    model_config = ConfigDict(extra="forbid")

    titles: list[StepTitle] = Field(min_length=1, max_length=MAX_STEPS_AT_ONCE)


class StepUpdate(BaseModel):
    """Partial update: a field that is absent is left alone. Neither can be ``null``."""

    model_config = ConfigDict(extra="forbid")

    # Defaults are not validated: omission is distinct from an explicit null, and only
    # supplied fields are forwarded to the application.
    title: StepTitle = Field(default=None)  # type: ignore[assignment]
    done: bool = Field(default=None)  # type: ignore[assignment]

    @model_validator(mode="before")
    @classmethod
    def _fields_cannot_be_null(cls, value: object) -> object:
        if isinstance(value, dict):
            for name in ("title", "done"):
                if name in value and value[name] is None:
                    raise ValueError(f"{name} cannot be null")
        return value

    def to_changes(self) -> StepChanges:
        return StepChanges(**{name: getattr(self, name) for name in self.model_fields_set})


class StepsOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_ids: list[uuid.UUID] = Field(
        max_length=MAX_STEPS_PER_TASK,
        description=(
            "Every step of the task, exactly once, in the order wanted; a task holds at most "
            "100 of them. A list that misses a step, repeats one, names a step of another "
            "task or is longer than the task may hold is rejected with `422`."
        ),
    )


class StepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    title: str
    done: bool
    position: int = Field(description="Where the step stands in its task: 0, 1, 2, ... no gaps.")
    created_at: datetime


class StepListResponse(BaseModel):
    items: list[StepResponse]

    @classmethod
    def of(cls, steps: Sequence[Step]) -> Self:
        return cls(items=[StepResponse.model_validate(step) for step in steps])
