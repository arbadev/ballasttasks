from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.steps import StepTitle
from app.application.step_generation import GenerationError, GenerationState
from app.application.use_cases.add_steps import MAX_STEPS_AT_ONCE


class StepGenerationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID
    state: GenerationState
    titles: list[StepTitle] = Field(
        max_length=MAX_STEPS_AT_ONCE,
        description=(
            "1-20 validated draft titles on success; empty in every other state. Not stored steps."
        ),
    )
    error: GenerationError | None
