"""Drafts are results, not stored steps. Only AddSteps accepts them into a task."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

GenerationState = Literal["pending", "running", "success", "failure"]
GenerationError = Literal[
    "invalid_output", "provider_unavailable", "timeout", "task_deleted", "worker_failed"
]

# Fixed resource/lifetime bounds, shared by the queue and worker.
GENERATION_RETENTION_SECONDS = 3600
GENERATION_DEADLINE_SECONDS = 300
GENERATION_MODEL_MAX_SECONDS = 240
MAX_COMPLETION_CHARACTERS = 32768


@dataclass(frozen=True, slots=True)
class GenerationOutcome:
    titles: tuple[str, ...] = ()
    error: GenerationError | None = None


@dataclass(frozen=True, slots=True)
class Generation:
    id: UUID
    task_id: UUID
    state: GenerationState
    titles: tuple[str, ...] = ()
    error: GenerationError | None = None


class GenerationNotFound(LookupError):  # noqa: N818 (matches TaskNotFound)
    def __init__(self) -> None:
        super().__init__("No retained generation for this task has that id")
